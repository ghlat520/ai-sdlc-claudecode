package com.srm.master.service;

import com.srm.common.dto.PageResponse;
import com.srm.master.dto.SupplierMasterDto;

public interface SupplierMasterService {

    SupplierMasterDto.Response createSupplier(SupplierMasterDto.CreateRequest request);

    SupplierMasterDto.Response updateSupplier(Long id, SupplierMasterDto.UpdateRequest request);

    SupplierMasterDto.Response getSupplier(Long id);

    void deleteSupplier(Long id);

    PageResponse<SupplierMasterDto.Response> listSuppliers(int page, int size);

    PageResponse<SupplierMasterDto.Response> searchSuppliers(String keyword, int page, int size);
}
