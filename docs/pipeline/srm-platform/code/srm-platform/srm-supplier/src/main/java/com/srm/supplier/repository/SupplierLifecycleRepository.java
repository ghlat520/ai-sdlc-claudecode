package com.srm.supplier.repository;

import com.srm.supplier.entity.SupplierLifecycle;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface SupplierLifecycleRepository extends JpaRepository<SupplierLifecycle, Long> {

    Optional<SupplierLifecycle> findBySupplierMasterIdAndDeletedFalse(Long supplierMasterId);

    Optional<SupplierLifecycle> findByIdAndTenantIdAndDeletedFalse(Long id, Long tenantId);
}
