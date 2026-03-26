package com.srm.receiving.service.impl;

import com.srm.common.context.TenantContext;
import com.srm.common.dto.PageResponse;
import com.srm.common.enums.PoStatus;
import com.srm.common.exception.BusinessException;
import com.srm.common.exception.ResourceNotFoundException;
import com.srm.purchase.entity.PoLineItem;
import com.srm.purchase.entity.PurchaseOrder;
import com.srm.purchase.repository.PoLineItemRepository;
import com.srm.purchase.repository.PurchaseOrderRepository;
import com.srm.receiving.dto.ReceivingDto;
import com.srm.receiving.entity.ReceivingRecord;
import com.srm.receiving.repository.ReceivingRecordRepository;
import com.srm.receiving.service.ReceivingService;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.List;

@Service
@Transactional
public class ReceivingServiceImpl implements ReceivingService {

    private final ReceivingRecordRepository receivingRepository;
    private final PurchaseOrderRepository poRepository;
    private final PoLineItemRepository lineItemRepository;

    public ReceivingServiceImpl(ReceivingRecordRepository receivingRepository,
                                 PurchaseOrderRepository poRepository,
                                 PoLineItemRepository lineItemRepository) {
        this.receivingRepository = receivingRepository;
        this.poRepository = poRepository;
        this.lineItemRepository = lineItemRepository;
    }

    @Override
    public ReceivingDto.ReceivingResponse receiveGoods(ReceivingDto.ReceiveRequest request) {
        Long tenantId = requireTenantId();

        PurchaseOrder po = poRepository.findByIdAndTenantIdAndDeletedFalse(request.poId(), tenantId)
                .orElseThrow(() -> new ResourceNotFoundException("PurchaseOrder", request.poId()));

        if (po.getStatus() != PoStatus.APPROVED
                && po.getStatus() != PoStatus.PARTIALLY_RECEIVED) {
            throw new BusinessException("INVALID_PO_STATE",
                    "Goods can only be received for APPROVED or PARTIALLY_RECEIVED purchase orders");
        }

        PoLineItem lineItem = lineItemRepository.findByIdAndDeletedFalse(request.poLineItemId())
                .orElseThrow(() -> new ResourceNotFoundException("PoLineItem", request.poLineItemId()));

        if (!lineItem.getPurchaseOrderId().equals(request.poId())) {
            throw new BusinessException("LINE_ITEM_MISMATCH",
                    "Line item does not belong to the specified PO");
        }

        // Validate over-receiving
        BigDecimal remainingQty = lineItem.getQuantity().subtract(lineItem.getReceivedQuantity());
        if (request.receivedQuantity().compareTo(remainingQty) > 0) {
            throw new BusinessException("OVER_RECEIVING",
                    String.format("Cannot receive %.4f, only %.4f remaining",
                            request.receivedQuantity(), remainingQty));
        }

        ReceivingRecord record = new ReceivingRecord();
        record.setPoId(request.poId());
        record.setPoLineItemId(request.poLineItemId());
        record.setReceivedQuantity(request.receivedQuantity());
        record.setReceivingDate(request.receivingDate());
        record.setWarehouseLocation(request.warehouseLocation());
        record.setBatchNumber(request.batchNumber());
        record.setReceivedById(request.receivedById());
        record.setTenantId(tenantId);

        ReceivingRecord saved = receivingRepository.save(record);

        // Update line item received quantity and status
        BigDecimal newReceivedQty = lineItem.getReceivedQuantity().add(request.receivedQuantity());
        lineItem.setReceivedQuantity(newReceivedQty);

        if (newReceivedQty.compareTo(lineItem.getQuantity()) >= 0) {
            lineItem.setStatus(PoLineItem.LineItemStatus.FULLY_RECEIVED);
        } else {
            lineItem.setStatus(PoLineItem.LineItemStatus.PARTIALLY_RECEIVED);
        }
        lineItemRepository.save(lineItem);

        // Update PO status based on all line items
        updatePoStatus(po, tenantId);

        return toResponse(saved);
    }

    @Override
    @Transactional(readOnly = true)
    public ReceivingDto.ReceivingResponse getReceiving(Long id) {
        Long tenantId = requireTenantId();
        ReceivingRecord record = receivingRepository.findByIdAndTenantIdAndDeletedFalse(id, tenantId)
                .orElseThrow(() -> new ResourceNotFoundException("ReceivingRecord", id));
        return toResponse(record);
    }

    @Override
    @Transactional(readOnly = true)
    public PageResponse<ReceivingDto.ReceivingResponse> listReceivings(int page, int size) {
        Long tenantId = requireTenantId();
        PageRequest pageable = PageRequest.of(page, size, Sort.by("createdAt").descending());
        Page<ReceivingRecord> result = receivingRepository
                .findByTenantIdAndDeletedFalse(tenantId, pageable);

        return PageResponse.of(
                result.getContent().stream().map(this::toResponse).toList(),
                result.getTotalElements(),
                page,
                size
        );
    }

    private void updatePoStatus(PurchaseOrder po, Long tenantId) {
        List<PoLineItem> allLineItems = lineItemRepository
                .findByPurchaseOrderIdAndDeletedFalse(po.getId());

        boolean allFullyReceived = allLineItems.stream()
                .allMatch(item -> item.getStatus() == PoLineItem.LineItemStatus.FULLY_RECEIVED);

        boolean anyReceived = allLineItems.stream()
                .anyMatch(item -> item.getStatus() != PoLineItem.LineItemStatus.OPEN);

        if (allFullyReceived) {
            po.setStatus(PoStatus.FULLY_RECEIVED);
        } else if (anyReceived) {
            po.setStatus(PoStatus.PARTIALLY_RECEIVED);
        }
        poRepository.save(po);
    }

    private Long requireTenantId() {
        Long tenantId = TenantContext.get();
        if (tenantId == null) {
            throw new BusinessException("TENANT_REQUIRED", "Tenant context is not set");
        }
        return tenantId;
    }

    private ReceivingDto.ReceivingResponse toResponse(ReceivingRecord record) {
        return new ReceivingDto.ReceivingResponse(
                record.getId(),
                record.getPoId(),
                record.getPoLineItemId(),
                record.getReceivedQuantity(),
                record.getReceivingDate(),
                record.getWarehouseLocation(),
                record.getBatchNumber(),
                record.getReceivedById(),
                record.getTenantId(),
                record.getCreatedAt()
        );
    }
}
