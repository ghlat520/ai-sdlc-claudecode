package com.srm.purchase.service;

import com.srm.common.dto.PageResponse;
import com.srm.purchase.dto.PurchaseOrderDto;

public interface PurchaseOrderService {

    PurchaseOrderDto.Response createPo(PurchaseOrderDto.CreateRequest request);

    PurchaseOrderDto.Response updatePo(Long id, PurchaseOrderDto.CreateRequest request);

    PurchaseOrderDto.Response submitForApproval(Long id);

    PurchaseOrderDto.Response approve(Long id, Long approverId, String remarks);

    PurchaseOrderDto.Response reject(Long id, Long reviewerId, String remarks);

    PurchaseOrderDto.Response cancel(Long id, String reason);

    PurchaseOrderDto.Response close(Long id);

    PurchaseOrderDto.Response getPo(Long id);

    PageResponse<PurchaseOrderDto.Response> listPos(int page, int size);

    PurchaseOrderDto.Response acknowledgeBySupplier(Long id);
}
