package com.srm.auth.entity;

import com.srm.common.entity.BaseEntity;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@Entity
@Table(name = "srm_permission")
public class Permission extends BaseEntity {

    @Column(name = "module", nullable = false, length = 64)
    private String module;

    @Enumerated(EnumType.STRING)
    @Column(name = "operation", nullable = false, length = 32)
    private Operation operation;

    @Column(name = "description", length = 256)
    private String description;

    public enum Operation {
        VIEW, CREATE, EDIT, DELETE, APPROVE, EXPORT
    }
}
