package com.srm.master.repository;

import com.srm.master.entity.SupplierMaster;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface SupplierMasterRepository extends JpaRepository<SupplierMaster, Long> {

    List<SupplierMaster> findByTenantIdAndDeletedFalse(Long tenantId);

    Page<SupplierMaster> findByTenantIdAndDeletedFalse(Long tenantId, Pageable pageable);

    Optional<SupplierMaster> findBySupplierCodeAndTenantId(String supplierCode, Long tenantId);

    Optional<SupplierMaster> findByIdAndTenantIdAndDeletedFalse(Long id, Long tenantId);

    @Query("SELECT s FROM SupplierMaster s WHERE s.tenantId = :tenantId AND s.deleted = false " +
           "AND (LOWER(s.companyName) LIKE LOWER(CONCAT('%', :keyword, '%')) " +
           "OR LOWER(s.supplierCode) LIKE LOWER(CONCAT('%', :keyword, '%')))")
    Page<SupplierMaster> searchByKeyword(@Param("tenantId") Long tenantId,
                                          @Param("keyword") String keyword,
                                          Pageable pageable);

    boolean existsBySupplierCodeAndDeletedFalse(String supplierCode);
}
