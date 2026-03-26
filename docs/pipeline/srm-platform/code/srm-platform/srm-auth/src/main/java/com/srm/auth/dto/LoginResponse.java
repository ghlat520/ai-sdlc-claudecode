package com.srm.auth.dto;

import java.util.List;

public record LoginResponse(
        String accessToken,
        String refreshToken,
        long expiresIn,
        Long userId,
        String username,
        List<String> roles,
        Long orgUnitId
) {
}
