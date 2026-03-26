package com.srm.purchase.repository;

import com.srm.purchase.entity.PoLineItem;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface PoLineItemRepository extends JpaRepository<PoLineItem, Long> {

    List<PoLineItem> findByPurchaseOrderIdAndDeletedFalse(Long purchaseOrderId);

    Optional<PoLineItem> findByIdAndDeletedFalse(Long id);
}
