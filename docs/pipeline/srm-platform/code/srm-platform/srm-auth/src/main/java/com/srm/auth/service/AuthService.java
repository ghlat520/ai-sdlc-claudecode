package com.srm.auth.service;

import com.srm.auth.dto.LoginRequest;
import com.srm.auth.dto.LoginResponse;
import com.srm.auth.dto.TokenResponse;

public interface AuthService {

    LoginResponse login(LoginRequest loginRequest);

    TokenResponse refresh(String refreshToken);

    void logout(Long userId);
}
