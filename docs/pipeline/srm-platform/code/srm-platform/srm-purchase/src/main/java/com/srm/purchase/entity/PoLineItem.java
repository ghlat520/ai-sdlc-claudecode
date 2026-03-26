package com.srm.purchase.entity;

import com.srm.common.entity.BaseEntity;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDate;

@Getter
@Setter
@Entity
@Table(name = "srm_po_line_item")
public class PoLineItem extends BaseEntity {

    @Column(name = "purchase_order_id", nullable = false)
    private Long purchaseOrderId;

    @Column(name = "material_id", nullable = false)
    private Long materialId;

    @Column(name = "quantity", nullable = false, precision = 18, scale = 4)
    private BigDecimal quantity;

    @Column(name = "unit_price", nullable = false, precision = 18, scale = 4)
    private BigDecimal unitPrice;

    @Column(name = "delivery_date")
    private LocalDate deliveryDate;

    @Column(name = "warehouse_location", length = 128)
    private String warehouseLocation;

    @Column(name = "received_quantity", nullable = false, precision = 18, scale = 4)
    private BigDecimal receivedQuantity = BigDecimal.ZERO;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 32)
    private LineItemStatus status = LineItemStatus.OPEN;

    public enum LineItemStatus {
        OPEN, PARTIALLY_RECEIVED, FULLY_RECEIVED
    }
}
