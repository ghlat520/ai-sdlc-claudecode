package com.srm.purchase.dto;

import com.srm.common.enums.PoStatus;
import com.srm.purchase.entity.PoLineItem;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

public class PurchaseOrderDto {

    public record LineItemRequest(
            @NotNull(message = "Material ID is required")
            Long materialId,

            @NotNull @Positive
            BigDecimal quantity,

            @NotNull @Positive
            BigDecimal unitPrice,

            LocalDate deliveryDate,

            String warehouseLocation
    ) {
    }

    public record CreateRequest(
            @NotNull(message = "Supplier ID is required")
            Long supplierId,

            String remarks,

            @NotEmpty(message = "At least one line item is required")
            @Valid
            List<LineItemRequest> lineItems
    ) {
    }

    public record LineItemResponse(
            Long id,
            Long materialId,
            BigDecimal quantity,
            BigDecimal unitPrice,
            LocalDate deliveryDate,
            String warehouseLocation,
            BigDecimal receivedQuantity,
            PoLineItem.LineItemStatus status
    ) {
    }

    public record Response(
            Long id,
            String poNumber,
            Long supplierId,
            PoStatus status,
            BigDecimal totalAmount,
            String approvalLevel,
            Long approvedBy,
            LocalDateTime approvedAt,
            String remarks,
            List<LineItemResponse> lineItems,
            Long tenantId,
            LocalDateTime createdAt,
            LocalDateTime updatedAt
    ) {
    }

    public record ApprovalRequest(
            String remarks
    ) {
    }
}
