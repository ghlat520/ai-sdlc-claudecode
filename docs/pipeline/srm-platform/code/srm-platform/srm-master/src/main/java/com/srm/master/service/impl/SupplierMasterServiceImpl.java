package com.srm.master.service.impl;

import com.srm.common.context.TenantContext;
import com.srm.common.dto.PageResponse;
import com.srm.common.exception.BusinessException;
import com.srm.common.exception.ResourceNotFoundException;
import com.srm.master.dto.SupplierMasterDto;
import com.srm.master.entity.SupplierMaster;
import com.srm.master.repository.SupplierMasterRepository;
import com.srm.master.service.SupplierMasterService;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;

@Service
@Transactional
public class SupplierMasterServiceImpl implements SupplierMasterService {

    private static final String SUPPLIER_CODE_PREFIX = "SUP";

    private final SupplierMasterRepository supplierMasterRepository;

    public SupplierMasterServiceImpl(SupplierMasterRepository supplierMasterRepository) {
        this.supplierMasterRepository = supplierMasterRepository;
    }

    @Override
    public SupplierMasterDto.Response createSupplier(SupplierMasterDto.CreateRequest request) {
        Long tenantId = requireTenantId();
        String supplierCode = generateSupplierCode();

        SupplierMaster supplier = new SupplierMaster();
        supplier.setSupplierCode(supplierCode);
        supplier.setCompanyName(request.companyName());
        supplier.setUscc(request.uscc());
        supplier.setContactName(request.contactName());
        supplier.setContactPhone(request.contactPhone());
        supplier.setContactEmail(request.contactEmail());
        supplier.setBankName(request.bankName());
        supplier.setBankAccount(request.bankAccount());
        supplier.setBusinessCategory(request.businessCategory());
        supplier.setAddress(request.address());
        supplier.setOrgUnitId(request.orgUnitId());
        supplier.setTenantId(tenantId);

        SupplierMaster saved = supplierMasterRepository.save(supplier);
        return toResponse(saved);
    }

    @Override
    public SupplierMasterDto.Response updateSupplier(Long id, SupplierMasterDto.UpdateRequest request) {
        Long tenantId = requireTenantId();
        SupplierMaster supplier = supplierMasterRepository
                .findByIdAndTenantIdAndDeletedFalse(id, tenantId)
                .orElseThrow(() -> new ResourceNotFoundException("SupplierMaster", id));

        supplier.setCompanyName(request.companyName());
        supplier.setUscc(request.uscc());
        supplier.setContactName(request.contactName());
        supplier.setContactPhone(request.contactPhone());
        supplier.setContactEmail(request.contactEmail());
        supplier.setBankName(request.bankName());
        supplier.setBankAccount(request.bankAccount());
        supplier.setBusinessCategory(request.businessCategory());
        supplier.setAddress(request.address());
        supplier.setOrgUnitId(request.orgUnitId());

        SupplierMaster saved = supplierMasterRepository.save(supplier);
        return toResponse(saved);
    }

    @Override
    @Transactional(readOnly = true)
    public SupplierMasterDto.Response getSupplier(Long id) {
        Long tenantId = requireTenantId();
        SupplierMaster supplier = supplierMasterRepository
                .findByIdAndTenantIdAndDeletedFalse(id, tenantId)
                .orElseThrow(() -> new ResourceNotFoundException("SupplierMaster", id));
        return toResponse(supplier);
    }

    @Override
    public void deleteSupplier(Long id) {
        Long tenantId = requireTenantId();
        SupplierMaster supplier = supplierMasterRepository
                .findByIdAndTenantIdAndDeletedFalse(id, tenantId)
                .orElseThrow(() -> new ResourceNotFoundException("SupplierMaster", id));
        supplier.setDeleted(true);
        supplierMasterRepository.save(supplier);
    }

    @Override
    @Transactional(readOnly = true)
    public PageResponse<SupplierMasterDto.Response> listSuppliers(int page, int size) {
        Long tenantId = requireTenantId();
        PageRequest pageable = PageRequest.of(page, size, Sort.by("createdAt").descending());
        Page<SupplierMaster> result = supplierMasterRepository
                .findByTenantIdAndDeletedFalse(tenantId, pageable);

        return PageResponse.of(
                result.getContent().stream().map(this::toResponse).toList(),
                result.getTotalElements(),
                page,
                size
        );
    }

    @Override
    @Transactional(readOnly = true)
    public PageResponse<SupplierMasterDto.Response> searchSuppliers(String keyword, int page, int size) {
        Long tenantId = requireTenantId();
        PageRequest pageable = PageRequest.of(page, size, Sort.by("createdAt").descending());
        Page<SupplierMaster> result = supplierMasterRepository
                .searchByKeyword(tenantId, keyword, pageable);

        return PageResponse.of(
                result.getContent().stream().map(this::toResponse).toList(),
                result.getTotalElements(),
                page,
                size
        );
    }

    private String generateSupplierCode() {
        String code;
        int attempts = 0;
        do {
            code = SUPPLIER_CODE_PREFIX + Instant.now().toEpochMilli();
            attempts++;
            if (attempts > 10) {
                throw new BusinessException("CODE_GENERATION_FAILED",
                        "Failed to generate unique supplier code");
            }
        } while (supplierMasterRepository.existsBySupplierCodeAndDeletedFalse(code));
        return code;
    }

    private Long requireTenantId() {
        Long tenantId = TenantContext.get();
        if (tenantId == null) {
            throw new BusinessException("TENANT_REQUIRED", "Tenant context is not set");
        }
        return tenantId;
    }

    private SupplierMasterDto.Response toResponse(SupplierMaster supplier) {
        return new SupplierMasterDto.Response(
                supplier.getId(),
                supplier.getSupplierCode(),
                supplier.getCompanyName(),
                supplier.getUscc(),
                supplier.getContactName(),
                supplier.getContactPhone(),
                supplier.getContactEmail(),
                supplier.getBankName(),
                supplier.getBankAccount(),
                supplier.getBusinessCategory(),
                supplier.getAddress(),
                supplier.getOrgUnitId(),
                supplier.getTenantId(),
                supplier.getCreatedAt(),
                supplier.getUpdatedAt()
        );
    }
}
