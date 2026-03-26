package com.srm.master.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import java.time.LocalDateTime;

public class SupplierMasterDto {

    public record CreateRequest(
            @NotBlank(message = "Company name is required")
            @Size(max = 256)
            String companyName,

            @Size(max = 64)
            String uscc,

            @Size(max = 128)
            String contactName,

            @Size(max = 32)
            String contactPhone,

            @Email
            @Size(max = 128)
            String contactEmail,

            @Size(max = 128)
            String bankName,

            @Size(max = 64)
            String bankAccount,

            @Size(max = 128)
            String businessCategory,

            @Size(max = 512)
            String address,

            Long orgUnitId
    ) {
    }

    public record UpdateRequest(
            @NotBlank(message = "Company name is required")
            @Size(max = 256)
            String companyName,

            @Size(max = 64)
            String uscc,

            @Size(max = 128)
            String contactName,

            @Size(max = 32)
            String contactPhone,

            @Email
            @Size(max = 128)
            String contactEmail,

            @Size(max = 128)
            String bankName,

            @Size(max = 64)
            String bankAccount,

            @Size(max = 128)
            String businessCategory,

            @Size(max = 512)
            String address,

            Long orgUnitId
    ) {
    }

    public record Response(
            Long id,
            String supplierCode,
            String companyName,
            String uscc,
            String contactName,
            String contactPhone,
            String contactEmail,
            String bankName,
            String bankAccount,
            String businessCategory,
            String address,
            Long orgUnitId,
            Long tenantId,
            LocalDateTime createdAt,
            LocalDateTime updatedAt
    ) {
    }
}
