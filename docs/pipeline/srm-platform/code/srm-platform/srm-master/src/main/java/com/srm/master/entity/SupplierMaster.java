package com.srm.master.entity;

import com.srm.common.entity.BaseEntity;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@Entity
@Table(name = "srm_supplier_master")
public class SupplierMaster extends BaseEntity {

    @Column(name = "supplier_code", nullable = false, unique = true, length = 32)
    private String supplierCode;

    @Column(name = "company_name", nullable = false, length = 256)
    private String companyName;

    @Column(name = "uscc", length = 64)
    private String uscc;

    @Column(name = "contact_name", length = 128)
    private String contactName;

    @Column(name = "contact_phone", length = 32)
    private String contactPhone;

    @Column(name = "contact_email", length = 128)
    private String contactEmail;

    @Column(name = "bank_name", length = 128)
    private String bankName;

    @Column(name = "bank_account", length = 64)
    private String bankAccount;

    @Column(name = "business_category", length = 128)
    private String businessCategory;

    @Column(name = "address", length = 512)
    private String address;

    @Column(name = "org_unit_id")
    private Long orgUnitId;
}
