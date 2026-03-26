package com.srm.supplier.entity;

import com.srm.common.entity.BaseEntity;
import com.srm.common.enums.SupplierState;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.Setter;

import java.time.LocalDateTime;

@Getter
@Setter
@Entity
@Table(name = "srm_state_transition")
public class StateTransitionRecord extends BaseEntity {

    @Column(name = "supplier_lifecycle_id", nullable = false)
    private Long supplierLifecycleId;

    @Enumerated(EnumType.STRING)
    @Column(name = "from_state", nullable = false, length = 32)
    private SupplierState fromState;

    @Enumerated(EnumType.STRING)
    @Column(name = "to_state", nullable = false, length = 32)
    private SupplierState toState;

    @Column(name = "reason", length = 512)
    private String reason;

    @Column(name = "operator_id")
    private Long operatorId;

    @Column(name = "operated_at", nullable = false)
    private LocalDateTime operatedAt;

    @Column(name = "ip_address", length = 64)
    private String ipAddress;
}
