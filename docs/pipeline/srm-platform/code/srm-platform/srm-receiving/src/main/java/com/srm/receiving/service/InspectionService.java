package com.srm.receiving.service;

import com.srm.receiving.dto.ReceivingDto;

public interface InspectionService {

    ReceivingDto.InspectionResponse recordInspection(ReceivingDto.InspectionRequest request);

    ReceivingDto.InspectionResponse getInspection(Long id);

    ReceivingDto.InspectionPassRateResponse getInspectionPassRate();
}
