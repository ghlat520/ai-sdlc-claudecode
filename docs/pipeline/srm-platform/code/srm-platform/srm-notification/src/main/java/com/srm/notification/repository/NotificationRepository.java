package com.srm.notification.repository;

import com.srm.notification.entity.Notification;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface NotificationRepository extends JpaRepository<Notification, Long> {

    Page<Notification> findByRecipientUserIdAndReadFalseAndDeletedFalse(Long userId, Pageable pageable);

    Optional<Notification> findByIdAndDeletedFalse(Long id);

    long countByRecipientUserIdAndReadFalseAndDeletedFalse(Long userId);
}
