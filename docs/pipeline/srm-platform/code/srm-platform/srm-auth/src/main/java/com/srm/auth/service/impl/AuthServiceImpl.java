package com.srm.auth.service.impl;

import com.srm.auth.dto.LoginRequest;
import com.srm.auth.dto.LoginResponse;
import com.srm.auth.dto.TokenResponse;
import com.srm.auth.entity.Role;
import com.srm.auth.entity.User;
import com.srm.auth.repository.UserRepository;
import com.srm.auth.security.JwtTokenProvider;
import com.srm.auth.service.AuthService;
import com.srm.common.exception.BusinessException;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
@Transactional
public class AuthServiceImpl implements AuthService {

    private final AuthenticationManager authenticationManager;
    private final JwtTokenProvider jwtTokenProvider;
    private final UserDetailsService userDetailsService;
    private final UserRepository userRepository;

    public AuthServiceImpl(AuthenticationManager authenticationManager,
                           JwtTokenProvider jwtTokenProvider,
                           UserDetailsService userDetailsService,
                           UserRepository userRepository) {
        this.authenticationManager = authenticationManager;
        this.jwtTokenProvider = jwtTokenProvider;
        this.userDetailsService = userDetailsService;
        this.userRepository = userRepository;
    }

    @Override
    public LoginResponse login(LoginRequest loginRequest) {
        try {
            Authentication authentication = authenticationManager.authenticate(
                    new UsernamePasswordAuthenticationToken(
                            loginRequest.username(), loginRequest.password()));

            UserDetails userDetails = (UserDetails) authentication.getPrincipal();
            User user = userRepository.findByUsernameAndDeletedFalse(loginRequest.username())
                    .orElseThrow(() -> new BusinessException("AUTH_ERROR", "User not found"));

            String accessToken = jwtTokenProvider.generateToken(
                    userDetails, user.getTenantId(), user.getOrgUnitId());
            String refreshToken = jwtTokenProvider.generateRefreshToken(userDetails);

            List<String> roles = user.getRoles().stream()
                    .map(Role::getName)
                    .toList();

            return new LoginResponse(
                    accessToken,
                    refreshToken,
                    jwtTokenProvider.getExpirationMs() / 1000,
                    user.getId(),
                    user.getUsername(),
                    roles,
                    user.getOrgUnitId()
            );
        } catch (BadCredentialsException e) {
            throw new BusinessException("INVALID_CREDENTIALS", "Invalid username or password");
        }
    }

    @Override
    public TokenResponse refresh(String refreshToken) {
        if (!jwtTokenProvider.validateToken(refreshToken)) {
            throw new BusinessException("INVALID_TOKEN", "Refresh token is invalid or expired");
        }

        String username = jwtTokenProvider.getUsernameFromToken(refreshToken);
        UserDetails userDetails = userDetailsService.loadUserByUsername(username);
        User user = userRepository.findByUsernameAndDeletedFalse(username)
                .orElseThrow(() -> new BusinessException("AUTH_ERROR", "User not found"));

        String newAccessToken = jwtTokenProvider.generateToken(
                userDetails, user.getTenantId(), user.getOrgUnitId());
        String newRefreshToken = jwtTokenProvider.generateRefreshToken(userDetails);

        return new TokenResponse(
                newAccessToken,
                newRefreshToken,
                jwtTokenProvider.getExpirationMs() / 1000
        );
    }

    @Override
    public void logout(Long userId) {
        // In a stateless JWT system, logout is handled client-side by discarding the token.
        // For server-side invalidation, a token blacklist (Redis) would be implemented here.
    }
}
