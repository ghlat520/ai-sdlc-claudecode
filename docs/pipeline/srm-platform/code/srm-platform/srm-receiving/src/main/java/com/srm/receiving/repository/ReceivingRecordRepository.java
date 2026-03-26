package com.srm.receiving.repository;

import com.srm.receiving.entity.ReceivingRecord;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface ReceivingRecordRepository extends JpaRepository<ReceivingRecord, Long> {

    Optional<ReceivingRecord> findByIdAndTenantIdAndDeletedFalse(Long id, Long tenantId);

    List<ReceivingRecord> findByPoLineItemIdAndDeletedFalse(Long poLineItemId);

    Page<ReceivingRecord> findByPoIdAndTenantIdAndDeletedFalse(Long poId, Long tenantId, Pageable pageable);

    Page<ReceivingRecord> findByTenantIdAndDeletedFalse(Long tenantId, Pageable pageable);
}
