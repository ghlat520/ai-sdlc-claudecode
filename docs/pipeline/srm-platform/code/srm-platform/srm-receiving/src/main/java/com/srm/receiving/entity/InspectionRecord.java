package com.srm.receiving.entity;

import com.srm.common.entity.BaseEntity;
import com.srm.common.enums.DefectCategory;
import com.srm.common.enums.DispositionAction;
import com.srm.common.enums.InspectionResult;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.Setter;

import java.time.LocalDateTime;

@Getter
@Setter
@Entity
@Table(name = "srm_inspection_record")
public class InspectionRecord extends BaseEntity {

    @Column(name = "receiving_record_id", nullable = false)
    private Long receivingRecordId;

    @Enumerated(EnumType.STRING)
    @Column(name = "inspection_result", nullable = false, length = 32)
    private InspectionResult inspectionResult;

    @Enumerated(EnumType.STRING)
    @Column(name = "defect_category", length = 32)
    private DefectCategory defectCategory;

    @Enumerated(EnumType.STRING)
    @Column(name = "disposition_action", length = 32)
    private DispositionAction dispositionAction;

    @Column(name = "remarks", length = 1024)
    private String remarks;

    @Column(name = "inspected_by_id")
    private Long inspectedById;

    @Column(name = "inspected_at")
    private LocalDateTime inspectedAt;

    @Column(name = "checklist_items", columnDefinition = "TEXT")
    private String checklistItems;
}
