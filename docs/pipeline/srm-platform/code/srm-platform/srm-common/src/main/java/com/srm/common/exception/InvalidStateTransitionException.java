package com.srm.common.exception;

import com.srm.common.enums.SupplierState;

import java.util.List;

public class InvalidStateTransitionException extends BusinessException {

    private final SupplierState currentState;
    private final SupplierState targetState;
    private final List<SupplierState> validTransitions;

    public InvalidStateTransitionException(
            SupplierState currentState,
            SupplierState targetState,
            List<SupplierState> validTransitions) {
        super("INVALID_STATE_TRANSITION",
                String.format("Cannot transition from %s to %s. Valid transitions: %s",
                        currentState, targetState, validTransitions));
        this.currentState = currentState;
        this.targetState = targetState;
        this.validTransitions = List.copyOf(validTransitions);
    }

    public SupplierState getCurrentState() {
        return currentState;
    }

    public SupplierState getTargetState() {
        return targetState;
    }

    public List<SupplierState> getValidTransitions() {
        return validTransitions;
    }
}
