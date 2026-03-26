package com.srm.supplier.fsm;

import com.srm.common.enums.SupplierState;
import com.srm.common.exception.InvalidStateTransitionException;
import com.srm.supplier.entity.StateTransitionRecord;
import com.srm.supplier.entity.SupplierLifecycle;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Component
public class SupplierStateMachine {

    private static final Map<SupplierState, Set<SupplierState>> VALID_TRANSITIONS;

    static {
        VALID_TRANSITIONS = new EnumMap<>(SupplierState.class);
        VALID_TRANSITIONS.put(SupplierState.PROSPECTIVE,
                Set.of(SupplierState.UNDER_REVIEW, SupplierState.DEACTIVATED));
        VALID_TRANSITIONS.put(SupplierState.UNDER_REVIEW,
                Set.of(SupplierState.APPROVED, SupplierState.DEACTIVATED));
        VALID_TRANSITIONS.put(SupplierState.APPROVED,
                Set.of(SupplierState.ACTIVE, SupplierState.DEACTIVATED));
        VALID_TRANSITIONS.put(SupplierState.ACTIVE,
                Set.of(SupplierState.SUSPENDED, SupplierState.BLACKLISTED, SupplierState.DEACTIVATED));
        VALID_TRANSITIONS.put(SupplierState.SUSPENDED,
                Set.of(SupplierState.ACTIVE, SupplierState.BLACKLISTED, SupplierState.DEACTIVATED));
        VALID_TRANSITIONS.put(SupplierState.BLACKLISTED,
                Set.of(SupplierState.DEACTIVATED));
        VALID_TRANSITIONS.put(SupplierState.DEACTIVATED,
                Set.of());
    }

    public StateTransitionRecord transition(SupplierLifecycle lifecycle,
                                            SupplierState targetState,
                                            String reason,
                                            Long operatorId) {
        SupplierState currentState = lifecycle.getCurrentState();
        Set<SupplierState> allowedTransitions = VALID_TRANSITIONS.getOrDefault(
                currentState, Set.of());

        if (!allowedTransitions.contains(targetState)) {
            throw new InvalidStateTransitionException(
                    currentState, targetState, List.copyOf(allowedTransitions));
        }

        StateTransitionRecord record = new StateTransitionRecord();
        record.setSupplierLifecycleId(lifecycle.getId());
        record.setFromState(currentState);
        record.setToState(targetState);
        record.setReason(reason);
        record.setOperatorId(operatorId);
        record.setOperatedAt(LocalDateTime.now());
        record.setTenantId(lifecycle.getTenantId());

        lifecycle.setCurrentState(targetState);

        return record;
    }

    public Set<SupplierState> getValidTransitions(SupplierState currentState) {
        return VALID_TRANSITIONS.getOrDefault(currentState, Set.of());
    }
}
