package com.srm.purchase.service.impl;

import com.srm.common.context.TenantContext;
import com.srm.common.dto.PageResponse;
import com.srm.common.enums.PoStatus;
import com.srm.common.exception.BusinessException;
import com.srm.common.exception.ResourceNotFoundException;
import com.srm.purchase.dto.PurchaseOrderDto;
import com.srm.purchase.entity.PoLineItem;
import com.srm.purchase.entity.PurchaseOrder;
import com.srm.purchase.repository.PoLineItemRepository;
import com.srm.purchase.repository.PurchaseOrderRepository;
import com.srm.purchase.service.PurchaseOrderService;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;

@Service
@Transactional
public class PurchaseOrderServiceImpl implements PurchaseOrderService {

    private static final String PO_NUMBER_PREFIX = "PO";
    private static final BigDecimal OFFICER_THRESHOLD = new BigDecimal("10000");
    private static final BigDecimal MANAGER_THRESHOLD = new BigDecimal("100000");

    private final PurchaseOrderRepository poRepository;
    private final PoLineItemRepository lineItemRepository;

    public PurchaseOrderServiceImpl(PurchaseOrderRepository poRepository,
                                     PoLineItemRepository lineItemRepository) {
        this.poRepository = poRepository;
        this.lineItemRepository = lineItemRepository;
    }

    @Override
    public PurchaseOrderDto.Response createPo(PurchaseOrderDto.CreateRequest request) {
        Long tenantId = requireTenantId();
        String poNumber = generatePoNumber();

        PurchaseOrder po = new PurchaseOrder();
        po.setPoNumber(poNumber);
        po.setSupplierId(request.supplierId());
        po.setStatus(PoStatus.DRAFT);
        po.setRemarks(request.remarks());
        po.setTenantId(tenantId);

        PurchaseOrder savedPo = poRepository.save(po);

        BigDecimal total = BigDecimal.ZERO;
        for (PurchaseOrderDto.LineItemRequest lineReq : request.lineItems()) {
            PoLineItem lineItem = buildLineItem(savedPo.getId(), lineReq, tenantId);
            lineItemRepository.save(lineItem);
            total = total.add(lineReq.quantity().multiply(lineReq.unitPrice()));
        }

        savedPo.setTotalAmount(total);
        savedPo.setApprovalLevel(determineApprovalLevel(total));
        PurchaseOrder finalPo = poRepository.save(savedPo);

        return toResponse(finalPo);
    }

    @Override
    public PurchaseOrderDto.Response updatePo(Long id, PurchaseOrderDto.CreateRequest request) {
        Long tenantId = requireTenantId();
        PurchaseOrder po = getPoByIdAndTenant(id, tenantId);

        if (po.getStatus() != PoStatus.DRAFT) {
            throw new BusinessException("INVALID_PO_STATE",
                    "Only DRAFT purchase orders can be updated");
        }

        po.setSupplierId(request.supplierId());
        po.setRemarks(request.remarks());

        // Remove existing line items and recreate
        List<PoLineItem> existingItems = lineItemRepository.findByPurchaseOrderIdAndDeletedFalse(id);
        existingItems.forEach(item -> {
            item.setDeleted(true);
            lineItemRepository.save(item);
        });

        BigDecimal total = BigDecimal.ZERO;
        for (PurchaseOrderDto.LineItemRequest lineReq : request.lineItems()) {
            PoLineItem lineItem = buildLineItem(po.getId(), lineReq, tenantId);
            lineItemRepository.save(lineItem);
            total = total.add(lineReq.quantity().multiply(lineReq.unitPrice()));
        }

        po.setTotalAmount(total);
        po.setApprovalLevel(determineApprovalLevel(total));

        PurchaseOrder saved = poRepository.save(po);
        return toResponse(saved);
    }

    @Override
    public PurchaseOrderDto.Response submitForApproval(Long id) {
        Long tenantId = requireTenantId();
        PurchaseOrder po = getPoByIdAndTenant(id, tenantId);

        if (po.getStatus() != PoStatus.DRAFT) {
            throw new BusinessException("INVALID_PO_STATE",
                    "Only DRAFT purchase orders can be submitted for approval");
        }

        po.setStatus(PoStatus.PENDING_APPROVAL);
        return toResponse(poRepository.save(po));
    }

    @Override
    public PurchaseOrderDto.Response approve(Long id, Long approverId, String remarks) {
        Long tenantId = requireTenantId();
        PurchaseOrder po = getPoByIdAndTenant(id, tenantId);

        if (po.getStatus() != PoStatus.PENDING_APPROVAL) {
            throw new BusinessException("INVALID_PO_STATE",
                    "Only PENDING_APPROVAL purchase orders can be approved");
        }

        po.setStatus(PoStatus.APPROVED);
        po.setApprovedBy(approverId);
        po.setApprovedAt(LocalDateTime.now());
        po.setRemarks(remarks);

        return toResponse(poRepository.save(po));
    }

    @Override
    public PurchaseOrderDto.Response reject(Long id, Long reviewerId, String remarks) {
        Long tenantId = requireTenantId();
        PurchaseOrder po = getPoByIdAndTenant(id, tenantId);

        if (po.getStatus() != PoStatus.PENDING_APPROVAL) {
            throw new BusinessException("INVALID_PO_STATE",
                    "Only PENDING_APPROVAL purchase orders can be rejected");
        }

        po.setStatus(PoStatus.DRAFT);
        po.setRemarks(remarks);

        return toResponse(poRepository.save(po));
    }

    @Override
    public PurchaseOrderDto.Response cancel(Long id, String reason) {
        Long tenantId = requireTenantId();
        PurchaseOrder po = getPoByIdAndTenant(id, tenantId);

        if (po.getStatus() == PoStatus.FULLY_RECEIVED
                || po.getStatus() == PoStatus.CLOSED
                || po.getStatus() == PoStatus.CANCELLED) {
            throw new BusinessException("INVALID_PO_STATE",
                    "Purchase order in status " + po.getStatus() + " cannot be cancelled");
        }

        po.setStatus(PoStatus.CANCELLED);
        po.setRemarks(reason);

        return toResponse(poRepository.save(po));
    }

    @Override
    public PurchaseOrderDto.Response close(Long id) {
        Long tenantId = requireTenantId();
        PurchaseOrder po = getPoByIdAndTenant(id, tenantId);

        if (po.getStatus() != PoStatus.FULLY_RECEIVED) {
            throw new BusinessException("INVALID_PO_STATE",
                    "Only FULLY_RECEIVED purchase orders can be closed");
        }

        po.setStatus(PoStatus.CLOSED);
        return toResponse(poRepository.save(po));
    }

    @Override
    @Transactional(readOnly = true)
    public PurchaseOrderDto.Response getPo(Long id) {
        Long tenantId = requireTenantId();
        PurchaseOrder po = getPoByIdAndTenant(id, tenantId);
        return toResponse(po);
    }

    @Override
    @Transactional(readOnly = true)
    public PageResponse<PurchaseOrderDto.Response> listPos(int page, int size) {
        Long tenantId = requireTenantId();
        PageRequest pageable = PageRequest.of(page, size, Sort.by("createdAt").descending());
        Page<PurchaseOrder> result = poRepository.findByTenantIdAndDeletedFalse(tenantId, pageable);

        return PageResponse.of(
                result.getContent().stream().map(this::toResponse).toList(),
                result.getTotalElements(),
                page,
                size
        );
    }

    @Override
    public PurchaseOrderDto.Response acknowledgeBySupplier(Long id) {
        Long tenantId = requireTenantId();
        PurchaseOrder po = getPoByIdAndTenant(id, tenantId);

        if (po.getStatus() != PoStatus.APPROVED) {
            throw new BusinessException("INVALID_PO_STATE",
                    "Only APPROVED purchase orders can be acknowledged");
        }

        // Supplier acknowledgement is recorded as a remark update
        po.setRemarks((po.getRemarks() != null ? po.getRemarks() + " | " : "") + "Acknowledged by supplier");
        return toResponse(poRepository.save(po));
    }

    private PurchaseOrder getPoByIdAndTenant(Long id, Long tenantId) {
        return poRepository.findByIdAndTenantIdAndDeletedFalse(id, tenantId)
                .orElseThrow(() -> new ResourceNotFoundException("PurchaseOrder", id));
    }

    private String generatePoNumber() {
        String timestamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"));
        String candidate = PO_NUMBER_PREFIX + timestamp;
        int suffix = 0;
        while (poRepository.existsByPoNumberAndDeletedFalse(candidate)) {
            suffix++;
            candidate = PO_NUMBER_PREFIX + timestamp + suffix;
        }
        return candidate;
    }

    private String determineApprovalLevel(BigDecimal totalAmount) {
        if (totalAmount.compareTo(OFFICER_THRESHOLD) < 0) {
            return "OFFICER";
        } else if (totalAmount.compareTo(MANAGER_THRESHOLD) < 0) {
            return "MANAGER";
        } else {
            return "DIRECTOR";
        }
    }

    private PoLineItem buildLineItem(Long poId, PurchaseOrderDto.LineItemRequest req, Long tenantId) {
        PoLineItem item = new PoLineItem();
        item.setPurchaseOrderId(poId);
        item.setMaterialId(req.materialId());
        item.setQuantity(req.quantity());
        item.setUnitPrice(req.unitPrice());
        item.setDeliveryDate(req.deliveryDate());
        item.setWarehouseLocation(req.warehouseLocation());
        item.setReceivedQuantity(BigDecimal.ZERO);
        item.setStatus(PoLineItem.LineItemStatus.OPEN);
        item.setTenantId(tenantId);
        return item;
    }

    private Long requireTenantId() {
        Long tenantId = TenantContext.get();
        if (tenantId == null) {
            throw new BusinessException("TENANT_REQUIRED", "Tenant context is not set");
        }
        return tenantId;
    }

    private PurchaseOrderDto.Response toResponse(PurchaseOrder po) {
        List<PoLineItem> lineItems = lineItemRepository.findByPurchaseOrderIdAndDeletedFalse(po.getId());
        List<PurchaseOrderDto.LineItemResponse> lineItemDtos = lineItems.stream()
                .map(item -> new PurchaseOrderDto.LineItemResponse(
                        item.getId(),
                        item.getMaterialId(),
                        item.getQuantity(),
                        item.getUnitPrice(),
                        item.getDeliveryDate(),
                        item.getWarehouseLocation(),
                        item.getReceivedQuantity(),
                        item.getStatus()
                ))
                .toList();

        return new PurchaseOrderDto.Response(
                po.getId(),
                po.getPoNumber(),
                po.getSupplierId(),
                po.getStatus(),
                po.getTotalAmount(),
                po.getApprovalLevel(),
                po.getApprovedBy(),
                po.getApprovedAt(),
                po.getRemarks(),
                lineItemDtos,
                po.getTenantId(),
                po.getCreatedAt(),
                po.getUpdatedAt()
        );
    }
}
