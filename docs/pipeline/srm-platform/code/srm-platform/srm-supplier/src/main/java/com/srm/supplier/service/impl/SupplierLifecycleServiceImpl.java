package com.srm.supplier.service.impl;

import com.srm.common.context.TenantContext;
import com.srm.common.enums.SupplierState;
import com.srm.common.exception.BusinessException;
import com.srm.common.exception.ResourceNotFoundException;
import com.srm.supplier.dto.SupplierLifecycleDto;
import com.srm.supplier.entity.StateTransitionRecord;
import com.srm.supplier.entity.SupplierLifecycle;
import com.srm.supplier.fsm.SupplierStateMachine;
import com.srm.supplier.repository.StateTransitionRecordRepository;
import com.srm.supplier.repository.SupplierLifecycleRepository;
import com.srm.supplier.service.SupplierLifecycleService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
@Transactional
public class SupplierLifecycleServiceImpl implements SupplierLifecycleService {

    private final SupplierLifecycleRepository lifecycleRepository;
    private final StateTransitionRecordRepository transitionRepository;
    private final SupplierStateMachine stateMachine;

    public SupplierLifecycleServiceImpl(SupplierLifecycleRepository lifecycleRepository,
                                         StateTransitionRecordRepository transitionRepository,
                                         SupplierStateMachine stateMachine) {
        this.lifecycleRepository = lifecycleRepository;
        this.transitionRepository = transitionRepository;
        this.stateMachine = stateMachine;
    }

    @Override
    public SupplierLifecycleDto.Response registerSupplier(Long supplierMasterId) {
        Long tenantId = requireTenantId();
        lifecycleRepository.findBySupplierMasterIdAndDeletedFalse(supplierMasterId)
                .ifPresent(existing -> {
                    throw new BusinessException("LIFECYCLE_EXISTS",
                            "Lifecycle already exists for supplier " + supplierMasterId);
                });

        SupplierLifecycle lifecycle = new SupplierLifecycle();
        lifecycle.setSupplierMasterId(supplierMasterId);
        lifecycle.setCurrentState(SupplierState.PROSPECTIVE);
        lifecycle.setTenantId(tenantId);

        SupplierLifecycle saved = lifecycleRepository.save(lifecycle);
        return toResponse(saved);
    }

    @Override
    public SupplierLifecycleDto.Response submitForReview(Long lifecycleId, String reason, Long operatorId) {
        return performTransition(lifecycleId, SupplierState.UNDER_REVIEW, reason, operatorId);
    }

    @Override
    public SupplierLifecycleDto.Response approve(Long lifecycleId, String reason, Long operatorId) {
        return performTransition(lifecycleId, SupplierState.APPROVED, reason, operatorId);
    }

    @Override
    public SupplierLifecycleDto.Response activate(Long lifecycleId, String reason, Long operatorId) {
        return performTransition(lifecycleId, SupplierState.ACTIVE, reason, operatorId);
    }

    @Override
    public SupplierLifecycleDto.Response suspend(Long lifecycleId, String reason, Long operatorId) {
        return performTransition(lifecycleId, SupplierState.SUSPENDED, reason, operatorId);
    }

    @Override
    public SupplierLifecycleDto.Response blacklist(Long lifecycleId, String reason, Long operatorId) {
        return performTransition(lifecycleId, SupplierState.BLACKLISTED, reason, operatorId);
    }

    @Override
    public SupplierLifecycleDto.Response deactivate(Long lifecycleId, String reason, Long operatorId) {
        return performTransition(lifecycleId, SupplierState.DEACTIVATED, reason, operatorId);
    }

    @Override
    @Transactional(readOnly = true)
    public SupplierLifecycleDto.Response getLifecycle(Long lifecycleId) {
        Long tenantId = requireTenantId();
        SupplierLifecycle lifecycle = lifecycleRepository
                .findByIdAndTenantIdAndDeletedFalse(lifecycleId, tenantId)
                .orElseThrow(() -> new ResourceNotFoundException("SupplierLifecycle", lifecycleId));
        return toResponse(lifecycle);
    }

    @Override
    @Transactional(readOnly = true)
    public SupplierLifecycleDto.Response getLifecycleBySupplierMasterId(Long supplierMasterId) {
        SupplierLifecycle lifecycle = lifecycleRepository
                .findBySupplierMasterIdAndDeletedFalse(supplierMasterId)
                .orElseThrow(() -> new ResourceNotFoundException(
                        "SupplierLifecycle for supplier " + supplierMasterId));
        return toResponse(lifecycle);
    }

    @Override
    @Transactional(readOnly = true)
    public List<SupplierLifecycleDto.TransitionRecordDto> getTransitionHistory(Long lifecycleId) {
        return transitionRepository
                .findBySupplierLifecycleIdOrderByOperatedAtDesc(lifecycleId)
                .stream()
                .map(this::toTransitionDto)
                .toList();
    }

    private SupplierLifecycleDto.Response performTransition(Long lifecycleId,
                                                             SupplierState targetState,
                                                             String reason,
                                                             Long operatorId) {
        Long tenantId = requireTenantId();
        SupplierLifecycle lifecycle = lifecycleRepository
                .findByIdAndTenantIdAndDeletedFalse(lifecycleId, tenantId)
                .orElseThrow(() -> new ResourceNotFoundException("SupplierLifecycle", lifecycleId));

        StateTransitionRecord record = stateMachine.transition(lifecycle, targetState, reason, operatorId);
        lifecycleRepository.save(lifecycle);
        transitionRepository.save(record);

        return toResponse(lifecycle);
    }

    private Long requireTenantId() {
        Long tenantId = TenantContext.get();
        if (tenantId == null) {
            throw new BusinessException("TENANT_REQUIRED", "Tenant context is not set");
        }
        return tenantId;
    }

    private SupplierLifecycleDto.Response toResponse(SupplierLifecycle lifecycle) {
        List<SupplierLifecycleDto.TransitionRecordDto> history = lifecycle.getStateHistory()
                .stream()
                .map(this::toTransitionDto)
                .toList();

        return new SupplierLifecycleDto.Response(
                lifecycle.getId(),
                lifecycle.getSupplierMasterId(),
                lifecycle.getCurrentState(),
                history,
                lifecycle.getTenantId(),
                lifecycle.getCreatedAt(),
                lifecycle.getUpdatedAt()
        );
    }

    private SupplierLifecycleDto.TransitionRecordDto toTransitionDto(StateTransitionRecord record) {
        return new SupplierLifecycleDto.TransitionRecordDto(
                record.getId(),
                record.getFromState(),
                record.getToState(),
                record.getReason(),
                record.getOperatorId(),
                record.getOperatedAt()
        );
    }
}
