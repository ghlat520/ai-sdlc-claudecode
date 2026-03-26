package com.srm.receiving.service.impl;

import com.srm.common.context.TenantContext;
import com.srm.common.enums.InspectionResult;
import com.srm.common.exception.BusinessException;
import com.srm.common.exception.ResourceNotFoundException;
import com.srm.receiving.dto.ReceivingDto;
import com.srm.receiving.entity.InspectionRecord;
import com.srm.receiving.entity.ReceivingRecord;
import com.srm.receiving.repository.InspectionRecordRepository;
import com.srm.receiving.repository.ReceivingRecordRepository;
import com.srm.receiving.service.InspectionService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

@Service
@Transactional
public class InspectionServiceImpl implements InspectionService {

    private final InspectionRecordRepository inspectionRepository;
    private final ReceivingRecordRepository receivingRepository;

    public InspectionServiceImpl(InspectionRecordRepository inspectionRepository,
                                  ReceivingRecordRepository receivingRepository) {
        this.inspectionRepository = inspectionRepository;
        this.receivingRepository = receivingRepository;
    }

    @Override
    public ReceivingDto.InspectionResponse recordInspection(ReceivingDto.InspectionRequest request) {
        Long tenantId = requireTenantId();

        ReceivingRecord receivingRecord = receivingRepository
                .findByIdAndTenantIdAndDeletedFalse(request.receivingRecordId(), tenantId)
                .orElseThrow(() -> new ResourceNotFoundException(
                        "ReceivingRecord", request.receivingRecordId()));

        // Check if inspection already exists
        inspectionRepository.findByReceivingRecordIdAndDeletedFalse(request.receivingRecordId())
                .ifPresent(existing -> {
                    throw new BusinessException("INSPECTION_EXISTS",
                            "Inspection already exists for receiving record " + request.receivingRecordId());
                });

        InspectionRecord record = new InspectionRecord();
        record.setReceivingRecordId(request.receivingRecordId());
        record.setInspectionResult(request.inspectionResult());
        record.setDefectCategory(request.defectCategory());
        record.setDispositionAction(request.dispositionAction());
        record.setRemarks(request.remarks());
        record.setInspectedById(request.inspectedById());
        record.setInspectedAt(LocalDateTime.now());
        record.setChecklistItems(request.checklistItems());
        record.setTenantId(tenantId);

        InspectionRecord saved = inspectionRepository.save(record);
        return toResponse(saved);
    }

    @Override
    @Transactional(readOnly = true)
    public ReceivingDto.InspectionResponse getInspection(Long id) {
        InspectionRecord record = inspectionRepository.findByIdAndDeletedFalse(id)
                .orElseThrow(() -> new ResourceNotFoundException("InspectionRecord", id));
        return toResponse(record);
    }

    @Override
    @Transactional(readOnly = true)
    public ReceivingDto.InspectionPassRateResponse getInspectionPassRate() {
        Long tenantId = requireTenantId();
        long total = inspectionRepository.countTotalByTenantId(tenantId);
        long passed = inspectionRepository.countByTenantIdAndResult(tenantId, InspectionResult.PASS);

        double passRate = total == 0 ? 0.0 : (double) passed / total * 100;

        return new ReceivingDto.InspectionPassRateResponse(total, passed, passRate);
    }

    private Long requireTenantId() {
        Long tenantId = TenantContext.get();
        if (tenantId == null) {
            throw new BusinessException("TENANT_REQUIRED", "Tenant context is not set");
        }
        return tenantId;
    }

    private ReceivingDto.InspectionResponse toResponse(InspectionRecord record) {
        return new ReceivingDto.InspectionResponse(
                record.getId(),
                record.getReceivingRecordId(),
                record.getInspectionResult(),
                record.getDefectCategory(),
                record.getDispositionAction(),
                record.getRemarks(),
                record.getInspectedById(),
                record.getInspectedAt(),
                record.getChecklistItems(),
                record.getTenantId(),
                record.getCreatedAt()
        );
    }
}
