package com.srm.supplier.service;

import com.srm.supplier.dto.SupplierLifecycleDto;

import java.util.List;

public interface SupplierLifecycleService {

    SupplierLifecycleDto.Response registerSupplier(Long supplierMasterId);

    SupplierLifecycleDto.Response submitForReview(Long lifecycleId, String reason, Long operatorId);

    SupplierLifecycleDto.Response approve(Long lifecycleId, String reason, Long operatorId);

    SupplierLifecycleDto.Response activate(Long lifecycleId, String reason, Long operatorId);

    SupplierLifecycleDto.Response suspend(Long lifecycleId, String reason, Long operatorId);

    SupplierLifecycleDto.Response blacklist(Long lifecycleId, String reason, Long operatorId);

    SupplierLifecycleDto.Response deactivate(Long lifecycleId, String reason, Long operatorId);

    SupplierLifecycleDto.Response getLifecycle(Long lifecycleId);

    SupplierLifecycleDto.Response getLifecycleBySupplierMasterId(Long supplierMasterId);

    List<SupplierLifecycleDto.TransitionRecordDto> getTransitionHistory(Long lifecycleId);
}
