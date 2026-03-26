package com.srm.web.controller;

import com.srm.common.dto.ApiResponse;
import com.srm.common.dto.PageResponse;
import com.srm.master.dto.SupplierMasterDto;
import com.srm.master.service.SupplierMasterService;
import com.srm.supplier.dto.SupplierLifecycleDto;
import com.srm.supplier.service.SupplierLifecycleService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/v1/suppliers")
public class SupplierController {

    private final SupplierMasterService supplierMasterService;
    private final SupplierLifecycleService supplierLifecycleService;

    public SupplierController(SupplierMasterService supplierMasterService,
                               SupplierLifecycleService supplierLifecycleService) {
        this.supplierMasterService = supplierMasterService;
        this.supplierLifecycleService = supplierLifecycleService;
    }

    @PostMapping
    @PreAuthorize("hasAuthority('SUPPLIER:CREATE')")
    public ResponseEntity<ApiResponse<SupplierMasterDto.Response>> createSupplier(
            @Valid @RequestBody SupplierMasterDto.CreateRequest request) {
        SupplierMasterDto.Response response = supplierMasterService.createSupplier(request);
        return ResponseEntity.status(HttpStatus.CREATED).body(ApiResponse.ok(response));
    }

    @GetMapping("/{id}")
    @PreAuthorize("hasAuthority('SUPPLIER:VIEW')")
    public ResponseEntity<ApiResponse<SupplierMasterDto.Response>> getSupplier(
            @PathVariable Long id) {
        SupplierMasterDto.Response response = supplierMasterService.getSupplier(id);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @PutMapping("/{id}")
    @PreAuthorize("hasAuthority('SUPPLIER:EDIT')")
    public ResponseEntity<ApiResponse<SupplierMasterDto.Response>> updateSupplier(
            @PathVariable Long id,
            @Valid @RequestBody SupplierMasterDto.UpdateRequest request) {
        SupplierMasterDto.Response response = supplierMasterService.updateSupplier(id, request);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @DeleteMapping("/{id}")
    @PreAuthorize("hasAuthority('SUPPLIER:DELETE')")
    public ResponseEntity<ApiResponse<Void>> deleteSupplier(@PathVariable Long id) {
        supplierMasterService.deleteSupplier(id);
        return ResponseEntity.ok(ApiResponse.ok(null, "Supplier deleted successfully"));
    }

    @GetMapping
    @PreAuthorize("hasAuthority('SUPPLIER:VIEW')")
    public ResponseEntity<ApiResponse<PageResponse<SupplierMasterDto.Response>>> listSuppliers(
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        PageResponse<SupplierMasterDto.Response> response = supplierMasterService.listSuppliers(page, size);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @GetMapping("/search")
    @PreAuthorize("hasAuthority('SUPPLIER:VIEW')")
    public ResponseEntity<ApiResponse<PageResponse<SupplierMasterDto.Response>>> searchSuppliers(
            @RequestParam String keyword,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        PageResponse<SupplierMasterDto.Response> response =
                supplierMasterService.searchSuppliers(keyword, page, size);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    // Lifecycle operations

    @PostMapping("/{id}/register")
    @PreAuthorize("hasAuthority('SUPPLIER:CREATE')")
    public ResponseEntity<ApiResponse<SupplierLifecycleDto.Response>> registerLifecycle(
            @PathVariable Long id) {
        SupplierLifecycleDto.Response response = supplierLifecycleService.registerSupplier(id);
        return ResponseEntity.status(HttpStatus.CREATED).body(ApiResponse.ok(response));
    }

    @GetMapping("/{id}/lifecycle")
    @PreAuthorize("hasAuthority('SUPPLIER:VIEW')")
    public ResponseEntity<ApiResponse<SupplierLifecycleDto.Response>> getLifecycle(
            @PathVariable Long id) {
        SupplierLifecycleDto.Response response =
                supplierLifecycleService.getLifecycleBySupplierMasterId(id);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @PostMapping("/lifecycle/{lifecycleId}/transition")
    @PreAuthorize("hasAuthority('SUPPLIER:APPROVE') or hasAuthority('SUPPLIER:EDIT')")
    public ResponseEntity<ApiResponse<SupplierLifecycleDto.Response>> transition(
            @PathVariable Long lifecycleId,
            @RequestBody SupplierLifecycleDto.TransitionRequest request,
            @RequestParam Long operatorId) {
        SupplierLifecycleDto.Response response = supplierLifecycleService.submitForReview(
                lifecycleId, request.reason(), operatorId);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @GetMapping("/lifecycle/{lifecycleId}/history")
    @PreAuthorize("hasAuthority('SUPPLIER:VIEW')")
    public ResponseEntity<ApiResponse<List<SupplierLifecycleDto.TransitionRecordDto>>> getHistory(
            @PathVariable Long lifecycleId) {
        List<SupplierLifecycleDto.TransitionRecordDto> history =
                supplierLifecycleService.getTransitionHistory(lifecycleId);
        return ResponseEntity.ok(ApiResponse.ok(history));
    }

    @PostMapping("/lifecycle/{lifecycleId}/approve")
    @PreAuthorize("hasAuthority('SUPPLIER:APPROVE')")
    public ResponseEntity<ApiResponse<SupplierLifecycleDto.Response>> approve(
            @PathVariable Long lifecycleId,
            @RequestParam String reason,
            @RequestParam Long operatorId) {
        SupplierLifecycleDto.Response response =
                supplierLifecycleService.approve(lifecycleId, reason, operatorId);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @PostMapping("/lifecycle/{lifecycleId}/activate")
    @PreAuthorize("hasAuthority('SUPPLIER:APPROVE')")
    public ResponseEntity<ApiResponse<SupplierLifecycleDto.Response>> activate(
            @PathVariable Long lifecycleId,
            @RequestParam String reason,
            @RequestParam Long operatorId) {
        SupplierLifecycleDto.Response response =
                supplierLifecycleService.activate(lifecycleId, reason, operatorId);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @PostMapping("/lifecycle/{lifecycleId}/suspend")
    @PreAuthorize("hasAuthority('SUPPLIER:APPROVE')")
    public ResponseEntity<ApiResponse<SupplierLifecycleDto.Response>> suspend(
            @PathVariable Long lifecycleId,
            @RequestParam String reason,
            @RequestParam Long operatorId) {
        SupplierLifecycleDto.Response response =
                supplierLifecycleService.suspend(lifecycleId, reason, operatorId);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @PostMapping("/lifecycle/{lifecycleId}/blacklist")
    @PreAuthorize("hasAuthority('SUPPLIER:APPROVE')")
    public ResponseEntity<ApiResponse<SupplierLifecycleDto.Response>> blacklist(
            @PathVariable Long lifecycleId,
            @RequestParam String reason,
            @RequestParam Long operatorId) {
        SupplierLifecycleDto.Response response =
                supplierLifecycleService.blacklist(lifecycleId, reason, operatorId);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }
}
