package com.srm.master.repository;

import com.srm.master.entity.Material;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface MaterialRepository extends JpaRepository<Material, Long> {

    Optional<Material> findByMaterialCodeAndDeletedFalse(String materialCode);

    Optional<Material> findByIdAndDeletedFalse(Long id);

    Page<Material> findByDeletedFalse(Pageable pageable);

    boolean existsByMaterialCodeAndDeletedFalse(String materialCode);
}
