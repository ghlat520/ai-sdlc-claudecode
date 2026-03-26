package com.srm.receiving.service;

import com.srm.common.dto.PageResponse;
import com.srm.receiving.dto.ReceivingDto;

public interface ReceivingService {

    ReceivingDto.ReceivingResponse receiveGoods(ReceivingDto.ReceiveRequest request);

    ReceivingDto.ReceivingResponse getReceiving(Long id);

    PageResponse<ReceivingDto.ReceivingResponse> listReceivings(int page, int size);
}
