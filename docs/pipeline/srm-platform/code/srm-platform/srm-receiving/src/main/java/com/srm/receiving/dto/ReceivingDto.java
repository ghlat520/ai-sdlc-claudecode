package com.srm.receiving.dto;

import com.srm.common.enums.DefectCategory;
import com.srm.common.enums.DispositionAction;
import com.srm.common.enums.InspectionResult;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

public class ReceivingDto {

    public record ReceiveRequest(
            @NotNull(message = "PO ID is required")
            Long poId,

            @NotNull(message = "PO line item ID is required")
            Long poLineItemId,

            @NotNull @Positive
            BigDecimal receivedQuantity,

            @NotNull
            LocalDate receivingDate,

            String warehouseLocation,

            String batchNumber,

            Long receivedById
    ) {
    }

    public record ReceivingResponse(
            Long id,
            Long poId,
            Long poLineItemId,
            BigDecimal receivedQuantity,
            LocalDate receivingDate,
            String warehouseLocation,
            String batchNumber,
            Long receivedById,
            Long tenantId,
            LocalDateTime createdAt
    ) {
    }

    public record InspectionRequest(
            @NotNull(message = "Receiving record ID is required")
            Long receivingRecordId,

            @NotNull(message = "Inspection result is required")
            InspectionResult inspectionResult,

            DefectCategory defectCategory,

            DispositionAction dispositionAction,

            String remarks,

            Long inspectedById,

            String checklistItems
    ) {
    }

    public record InspectionResponse(
            Long id,
            Long receivingRecordId,
            InspectionResult inspectionResult,
            DefectCategory defectCategory,
            DispositionAction dispositionAction,
            String remarks,
            Long inspectedById,
            LocalDateTime inspectedAt,
            String checklistItems,
            Long tenantId,
            LocalDateTime createdAt
    ) {
    }

    public record InspectionPassRateResponse(
            long totalInspections,
            long passedInspections,
            double passRate
    ) {
    }
}
