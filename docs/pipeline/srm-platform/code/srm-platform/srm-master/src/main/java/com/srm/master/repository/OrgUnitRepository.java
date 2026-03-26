package com.srm.master.repository;

import com.srm.master.entity.OrgUnit;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface OrgUnitRepository extends JpaRepository<OrgUnit, Long> {

    Optional<OrgUnit> findByCodeAndDeletedFalse(String code);

    Optional<OrgUnit> findByIdAndDeletedFalse(Long id);

    List<OrgUnit> findByParentIdAndDeletedFalse(Long parentId);

    List<OrgUnit> findByTenantIdAndDeletedFalse(Long tenantId);
}
