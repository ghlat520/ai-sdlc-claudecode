package com.srm.master.entity;

import com.srm.common.entity.BaseEntity;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@Entity
@Table(name = "srm_material")
public class Material extends BaseEntity {

    @Column(name = "material_code", nullable = false, unique = true, length = 32)
    private String materialCode;

    @Column(name = "material_name", nullable = false, length = 256)
    private String materialName;

    @Column(name = "specification", length = 512)
    private String specification;

    @Column(name = "unit", length = 32)
    private String unit;

    @Column(name = "category", length = 128)
    private String category;

    @Column(name = "description", length = 1024)
    private String description;
}
