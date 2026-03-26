package com.srm.purchase.repository;

import com.srm.common.enums.PoStatus;
import com.srm.purchase.entity.PurchaseOrder;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface PurchaseOrderRepository extends JpaRepository<PurchaseOrder, Long> {

    Optional<PurchaseOrder> findByIdAndTenantIdAndDeletedFalse(Long id, Long tenantId);

    Optional<PurchaseOrder> findByPoNumberAndTenantId(String poNumber, Long tenantId);

    Page<PurchaseOrder> findByTenantIdAndDeletedFalse(Long tenantId, Pageable pageable);

    Page<PurchaseOrder> findByTenantIdAndStatusAndDeletedFalse(Long tenantId,
                                                                PoStatus status,
                                                                Pageable pageable);

    boolean existsByPoNumberAndDeletedFalse(String poNumber);
}
