package com.srm.common.adapter;

public interface PoDataExchangeAdapter {

    default void exchangePoData(Long poId) {
        // No-op default implementation
    }

    default void syncPoStatus(Long poId, String status) {
        // No-op default implementation
    }
}
