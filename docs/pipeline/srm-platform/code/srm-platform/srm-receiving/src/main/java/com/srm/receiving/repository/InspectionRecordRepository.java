package com.srm.receiving.repository;

import com.srm.common.enums.InspectionResult;
import com.srm.receiving.entity.InspectionRecord;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface InspectionRecordRepository extends JpaRepository<InspectionRecord, Long> {

    Optional<InspectionRecord> findByReceivingRecordIdAndDeletedFalse(Long receivingRecordId);

    Optional<InspectionRecord> findByIdAndDeletedFalse(Long id);

    List<InspectionRecord> findByTenantIdAndDeletedFalse(Long tenantId);

    @Query("SELECT COUNT(i) FROM InspectionRecord i WHERE i.tenantId = :tenantId AND i.deleted = false")
    long countTotalByTenantId(@Param("tenantId") Long tenantId);

    @Query("SELECT COUNT(i) FROM InspectionRecord i WHERE i.tenantId = :tenantId " +
           "AND i.deleted = false AND i.inspectionResult = :result")
    long countByTenantIdAndResult(@Param("tenantId") Long tenantId,
                                  @Param("result") InspectionResult result);
}
