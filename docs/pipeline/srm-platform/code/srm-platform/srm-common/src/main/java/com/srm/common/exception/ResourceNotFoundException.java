package com.srm.common.exception;

public class ResourceNotFoundException extends BusinessException {

    public ResourceNotFoundException(String resourceType, Long id) {
        super("RESOURCE_NOT_FOUND",
                String.format("%s with id %d not found", resourceType, id));
    }

    public ResourceNotFoundException(String message) {
        super("RESOURCE_NOT_FOUND", message);
    }
}
