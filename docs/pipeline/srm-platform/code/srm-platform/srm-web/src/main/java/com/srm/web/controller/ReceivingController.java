package com.srm.web.controller;

import com.srm.common.dto.ApiResponse;
import com.srm.common.dto.PageResponse;
import com.srm.receiving.dto.ReceivingDto;
import com.srm.receiving.service.InspectionService;
import com.srm.receiving.service.ReceivingService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/receivings")
public class ReceivingController {

    private final ReceivingService receivingService;
    private final InspectionService inspectionService;

    public ReceivingController(ReceivingService receivingService,
                                InspectionService inspectionService) {
        this.receivingService = receivingService;
        this.inspectionService = inspectionService;
    }

    @PostMapping
    @PreAuthorize("hasAuthority('RECEIVING:CREATE')")
    public ResponseEntity<ApiResponse<ReceivingDto.ReceivingResponse>> receiveGoods(
            @Valid @RequestBody ReceivingDto.ReceiveRequest request) {
        ReceivingDto.ReceivingResponse response = receivingService.receiveGoods(request);
        return ResponseEntity.status(HttpStatus.CREATED).body(ApiResponse.ok(response));
    }

    @GetMapping("/{id}")
    @PreAuthorize("hasAuthority('RECEIVING:VIEW')")
    public ResponseEntity<ApiResponse<ReceivingDto.ReceivingResponse>> getReceiving(
            @PathVariable Long id) {
        ReceivingDto.ReceivingResponse response = receivingService.getReceiving(id);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @GetMapping
    @PreAuthorize("hasAuthority('RECEIVING:VIEW')")
    public ResponseEntity<ApiResponse<PageResponse<ReceivingDto.ReceivingResponse>>> listReceivings(
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        PageResponse<ReceivingDto.ReceivingResponse> response =
                receivingService.listReceivings(page, size);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @PostMapping("/inspections")
    @PreAuthorize("hasAuthority('RECEIVING:CREATE')")
    public ResponseEntity<ApiResponse<ReceivingDto.InspectionResponse>> recordInspection(
            @Valid @RequestBody ReceivingDto.InspectionRequest request) {
        ReceivingDto.InspectionResponse response = inspectionService.recordInspection(request);
        return ResponseEntity.status(HttpStatus.CREATED).body(ApiResponse.ok(response));
    }

    @GetMapping("/inspections/{id}")
    @PreAuthorize("hasAuthority('RECEIVING:VIEW')")
    public ResponseEntity<ApiResponse<ReceivingDto.InspectionResponse>> getInspection(
            @PathVariable Long id) {
        ReceivingDto.InspectionResponse response = inspectionService.getInspection(id);
        return ResponseEntity.ok(ApiResponse.ok(response));
    }

    @GetMapping("/inspections/pass-rate")
    @PreAuthorize("hasAuthority('RECEIVING:VIEW')")
    public ResponseEntity<ApiResponse<ReceivingDto.InspectionPassRateResponse>> getPassRate() {
        ReceivingDto.InspectionPassRateResponse response = inspectionService.getInspectionPassRate();
        return ResponseEntity.ok(ApiResponse.ok(response));
    }
}
