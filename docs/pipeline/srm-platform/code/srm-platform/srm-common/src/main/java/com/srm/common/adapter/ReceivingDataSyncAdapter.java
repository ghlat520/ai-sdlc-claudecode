package com.srm.common.adapter;

public interface ReceivingDataSyncAdapter {

    default void syncReceiving(Long receivingId) {
        // No-op default implementation
    }
}
