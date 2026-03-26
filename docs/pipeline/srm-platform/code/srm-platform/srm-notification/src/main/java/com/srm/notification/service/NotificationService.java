package com.srm.notification.service;

import com.srm.notification.entity.Notification;
import org.springframework.data.domain.Page;

public interface NotificationService {

    void sendInApp(Long userId, String eventType, String title, String body);

    void sendEmail(String email, String subject, String body);

    void markAsRead(Long notificationId);

    Page<Notification> listUnread(Long userId, int page, int size);

    long countUnread(Long userId);
}
