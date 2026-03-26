package com.srm.common.adapter;

public interface SupplierMasterSyncAdapter {

    default void syncSupplier(Long supplierId) {
        // No-op default implementation
    }
}
