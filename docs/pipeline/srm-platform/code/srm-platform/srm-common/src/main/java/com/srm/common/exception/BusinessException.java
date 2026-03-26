package com.srm.common.exception;

public class BusinessException extends RuntimeException {

    private final String code;

    public BusinessException(String code, String message) {
        super(message);
        this.code = code;
    }

    public BusinessException(String message) {
        super(message);
        this.code = "BUSINESS_ERROR";
    }

    public String getCode() {
        return code;
    }
}
