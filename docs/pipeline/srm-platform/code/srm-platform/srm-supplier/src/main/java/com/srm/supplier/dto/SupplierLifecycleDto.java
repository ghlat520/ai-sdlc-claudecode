package com.srm.supplier.dto;

import com.srm.common.enums.SupplierState;

import java.time.LocalDateTime;
import java.util.List;

public class SupplierLifecycleDto {

    public record Response(
            Long id,
            Long supplierMasterId,
            SupplierState currentState,
            List<TransitionRecordDto> recentTransitions,
            Long tenantId,
            LocalDateTime createdAt,
            LocalDateTime updatedAt
    ) {
    }

    public record TransitionRecordDto(
            Long id,
            SupplierState fromState,
            SupplierState toState,
            String reason,
            Long operatorId,
            LocalDateTime operatedAt
    ) {
    }

    public record TransitionRequest(
            SupplierState targetState,
            String reason
    ) {
    }
}
