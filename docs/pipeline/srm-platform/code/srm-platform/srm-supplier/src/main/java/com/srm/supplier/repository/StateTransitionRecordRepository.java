package com.srm.supplier.repository;

import com.srm.supplier.entity.StateTransitionRecord;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface StateTransitionRecordRepository extends JpaRepository<StateTransitionRecord, Long> {

    List<StateTransitionRecord> findBySupplierLifecycleIdOrderByOperatedAtDesc(Long supplierLifecycleId);
}
