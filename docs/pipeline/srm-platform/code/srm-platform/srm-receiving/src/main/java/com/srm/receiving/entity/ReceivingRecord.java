package com.srm.receiving.entity;

import com.srm.common.entity.BaseEntity;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDate;

@Getter
@Setter
@Entity
@Table(name = "srm_receiving_record")
public class ReceivingRecord extends BaseEntity {

    @Column(name = "po_id", nullable = false)
    private Long poId;

    @Column(name = "po_line_item_id", nullable = false)
    private Long poLineItemId;

    @Column(name = "received_quantity", nullable = false, precision = 18, scale = 4)
    private BigDecimal receivedQuantity;

    @Column(name = "receiving_date", nullable = false)
    private LocalDate receivingDate;

    @Column(name = "warehouse_location", length = 128)
    private String warehouseLocation;

    @Column(name = "batch_number", length = 64)
    private String batchNumber;

    @Column(name = "received_by_id")
    private Long receivedById;
}
