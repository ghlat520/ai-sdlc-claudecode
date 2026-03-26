package com.srm.notification.service.impl;

import com.srm.common.context.TenantContext;
import com.srm.common.exception.ResourceNotFoundException;
import com.srm.notification.entity.Notification;
import com.srm.notification.repository.NotificationRepository;
import com.srm.notification.service.NotificationService;
import jakarta.mail.MessagingException;
import jakarta.mail.internet.MimeMessage;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.MimeMessageHelper;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional
public class NotificationServiceImpl implements NotificationService {

    private static final Logger log = LoggerFactory.getLogger(NotificationServiceImpl.class);

    private final NotificationRepository notificationRepository;
    private final JavaMailSender mailSender;

    public NotificationServiceImpl(NotificationRepository notificationRepository,
                                    JavaMailSender mailSender) {
        this.notificationRepository = notificationRepository;
        this.mailSender = mailSender;
    }

    @Override
    @Async
    public void sendInApp(Long userId, String eventType, String title, String body) {
        Notification notification = new Notification();
        notification.setRecipientUserId(userId);
        notification.setEventType(eventType);
        notification.setTitle(title);
        notification.setBody(body);
        notification.setRead(false);

        Long tenantId = TenantContext.get();
        if (tenantId != null) {
            notification.setTenantId(tenantId);
        }

        notificationRepository.save(notification);
        log.info("In-app notification sent to user {} for event {}", userId, eventType);
    }

    @Override
    @Async
    public void sendEmail(String email, String subject, String body) {
        try {
            MimeMessage message = mailSender.createMimeMessage();
            MimeMessageHelper helper = new MimeMessageHelper(message, true, "UTF-8");
            helper.setTo(email);
            helper.setSubject(subject);
            helper.setText(body, true);
            mailSender.send(message);
            log.info("Email notification sent to {}", email);
        } catch (MessagingException e) {
            log.error("Failed to send email to {}: {}", email, e.getMessage(), e);
            throw new RuntimeException("Failed to send email notification", e);
        }
    }

    @Override
    public void markAsRead(Long notificationId) {
        Notification notification = notificationRepository.findByIdAndDeletedFalse(notificationId)
                .orElseThrow(() -> new ResourceNotFoundException("Notification", notificationId));
        notification.setRead(true);
        notificationRepository.save(notification);
    }

    @Override
    @Transactional(readOnly = true)
    public Page<Notification> listUnread(Long userId, int page, int size) {
        PageRequest pageable = PageRequest.of(page, size, Sort.by("createdAt").descending());
        return notificationRepository.findByRecipientUserIdAndReadFalseAndDeletedFalse(userId, pageable);
    }

    @Override
    @Transactional(readOnly = true)
    public long countUnread(Long userId) {
        return notificationRepository.countByRecipientUserIdAndReadFalseAndDeletedFalse(userId);
    }
}
