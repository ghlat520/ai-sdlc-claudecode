package com.srm.supplier.entity;

import com.srm.common.entity.BaseEntity;
import com.srm.common.enums.SupplierState;
import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.OneToMany;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.Setter;

import java.util.ArrayList;
import java.util.List;

@Getter
@Setter
@Entity
@Table(name = "srm_supplier_lifecycle")
public class SupplierLifecycle extends BaseEntity {

    @Column(name = "supplier_master_id", nullable = false)
    private Long supplierMasterId;

    @Enumerated(EnumType.STRING)
    @Column(name = "current_state", nullable = false, length = 32)
    private SupplierState currentState;

    @OneToMany(mappedBy = "supplierLifecycleId", cascade = CascadeType.ALL, fetch = FetchType.LAZY)
    private List<StateTransitionRecord> stateHistory = new ArrayList<>();
}
