package com.srm.web.controller;

import com.srm.common.dto.ApiResponse;
import com.srm.common.dto.PageResponse;
import com.srm.purchase.dto.PurchaseOrderDto;
import com.srm.purchase.service.PurchaseOrderService;
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

@RestController
@RequestMapping("/api/v1/purchase-orders")
public class PurchaseOrderController {

    private final PurchaseOrderService purchaseOrderService;

    public PurchaseOrderController(PurchaseOrderService purchaseOrderService) {
        this.purchaseOrderService = purchaseOrderService;
    }

    @PostMapping
    @PreAuthorize("hasAuthority('PURCHASE_ORDER:CREATE')")
    public ResponseEntity<ApiResponse<PurchaseOrderDto.Response>> createPo(
            @Valid @RequestBody PurchaseOrderDto.CreateRequest request) {
        PurchaseOrderDto.Response response = purchaseOrderService.createPo(request);
        return ResponseEntity.status(HttpStatus.CREATED).body(ApiResponse.ok(response));
    }

    @GetMapping("/{id}")
    @PreAuthorize("hasAuthority('PURCHASE_ORDER:VIEW')")
    public ResponseEntity<ApiResponse<PurchaseOrderDto.Response>> getPo(@PathVariable Long id) {
        PurchaseOrderDto.Response response = purchaseOrderService.getPo(id);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @PutMapping("/{id}")
    @PreAuthorize("hasAuthority('PURCHASE_ORDER:EDIT')")
    public ResponseEntity<ApiResponse<PurchaseOrderDto.Response>> updatePo(
            @PathVariable Long id,
            @Valid @RequestBody PurchaseOrderDto.CreateRequest request) {
        PurchaseOrderDto.Response response = purchaseOrderService.updatePo(id, request);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @GetMapping
    @PreAuthorize("hasAuthority('PURCHASE_ORDER:VIEW')")
    public ResponseEntity<ApiResponse<PageResponse<PurchaseOrderDto.Response>>> listPos(
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        PageResponse<PurchaseOrderDto.Response> response = purchaseOrderService.listPos(page, size);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @PostMapping("/{id}/submit")
    @PreAuthorize("hasAuthority('PURCHASE_ORDER:EDIT')")
    public ResponseEntity<ApiResponse<PurchaseOrderDto.Response>> submitForApproval(
            @PathVariable Long id) {
        PurchaseOrderDto.Response response = purchaseOrderService.submitForApproval(id);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @PostMapping("/{id}/approve")
    @PreAuthorize("hasAuthority('PURCHASE_ORDER:APPROVE')")
    public ResponseEntity<ApiResponse<PurchaseOrderDto.Response>> approve(
            @PathVariable Long id,
            @RequestParam Long approverId,
            @RequestBody(required = false) PurchaseOrderDto.ApprovalRequest approvalRequest) {
        String remarks = approvalRequest != null ? approvalRequest.remarks() : null;
        PurchaseOrderDto.Response response = purchaseOrderService.approve(id, approverId, remarks);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @PostMapping("/{id}/reject")
    @PreAuthorize("hasAuthority('PURCHASE_ORDER:APPROVE')")
    public ResponseEntity<ApiResponse<PurchaseOrderDto.Response>> reject(
            @PathVariable Long id,
            @RequestParam Long reviewerId,
            @RequestBody(required = false) PurchaseOrderDto.ApprovalRequest approvalRequest) {
        String remarks = approvalRequest != null ? approvalRequest.remarks() : null;
        PurchaseOrderDto.Response response = purchaseOrderService.reject(id, reviewerId, remarks);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @DeleteMapping("/{id}/cancel")
    @PreAuthorize("hasAuthority('PURCHASE_ORDER:EDIT')")
    public ResponseEntity<ApiResponse<PurchaseOrderDto.Response>> cancel(
            @PathVariable Long id,
            @RequestParam(required = false) String reason) {
        PurchaseOrderDto.Response response = purchaseOrderService.cancel(id, reason);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @PostMapping("/{id}/close")
    @PreAuthorize("hasAuthority('PURCHASE_ORDER:EDIT')")
    public ResponseEntity<ApiResponse<PurchaseOrderDto.Response>> close(@PathVariable Long id) {
        PurchaseOrderDto.Response response = purchaseOrderService.close(id);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @PostMapping("/{id}/acknowledge")
    @PreAuthorize("hasAuthority('PURCHASE_ORDER:EDIT')")
    public ResponseEntity<ApiResponse<PurchaseOrderDto.Response>> acknowledge(@PathVariable Long id) {
        PurchaseOrderDto.Response response = purchaseOrderService.acknowledgeBySupplier(id);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }
}
