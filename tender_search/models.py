# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models
from django.contrib.postgres.fields import ArrayField
class Costingsheetdetails(models.Model):
    itemcode = models.TextField(db_column='itemCode')  # Field name made lowercase.
    itemschedule = models.TextField(db_column='itemSchedule', blank=True, null=True)  # Field name made lowercase.
    proposederpitemname = models.TextField(db_column='proposedErpItemName', blank=True, null=True)  # Field name made lowercase.
    proposederpquantity = models.TextField(db_column='proposedErpQuantity', blank=True, null=True)  # Field name made lowercase.
    priceoffullquantity = models.TextField(db_column='priceOfFullQuantity', blank=True, null=True)  # Field name made lowercase.
    cva = models.TextField(blank=True, null=True)
    tendermergedid = models.ForeignKey('TenderMerged', models.DO_NOTHING, db_column='tenderMergedId', blank=True, null=True)  # Field name made lowercase.
    createdat = models.DateTimeField(db_column='createdAt')  # Field name made lowercase.
    updatedat = models.DateTimeField(db_column='updatedAt')  # Field name made lowercase.
    location = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'CostingSheetDetails'

class Items(models.Model):
    itemcode = models.TextField(unique=True)
    itemname = models.TextField(db_column='itemName')  # Field name made lowercase.
    itemschedule = models.TextField(db_column='itemSchedule')  # Field name made lowercase.
    createdat = models.DateTimeField(db_column='createdAt')  # Field name made lowercase.
    updatedat = models.DateTimeField(db_column='updatedAt')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'Items'

class Files(models.Model):
    filename = models.TextField(db_column='fileName')  # Field name made lowercase.
    filepath = models.TextField(db_column='filePath', blank=True, null=True)  # Field name made lowercase.
    filetype = models.TextField(db_column='fileType', blank=True, null=True)  # Field name made lowercase.
    filesize = models.IntegerField(db_column='fileSize', blank=True, null=True)  # Field name made lowercase.
    uploadedby = models.TextField(db_column='uploadedBy', blank=True, null=True)  # Field name made lowercase.
    status = models.TextField(blank=True, null=True)
    totalcount = models.IntegerField(db_column='totalCount', blank=True, null=True)  # Field name made lowercase.
    excludedcount = models.IntegerField(db_column='excludedCount', blank=True, null=True)  # Field name made lowercase.
    createdat = models.DateTimeField(db_column='createdAt')  # Field name made lowercase.
    updatedat = models.DateTimeField(db_column='updatedAt')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'files'


class GemTenders(models.Model):
    fileid = models.ForeignKey(Files, models.DO_NOTHING, db_column='fileId')  # Field name made lowercase.
    referenceno = models.TextField(db_column='referenceNo', unique=True)  # Field name made lowercase.
    tenderbrief = models.TextField(db_column='tenderBrief', blank=True, null=True)  # Field name made lowercase.
    value = models.TextField(blank=True, null=True)
    deadline = models.DateTimeField(blank=True, null=True)
    location = models.TextField(blank=True, null=True)
    organization = models.TextField(blank=True, null=True)
    documentfees = models.TextField(db_column='documentFees', blank=True, null=True)  # Field name made lowercase.
    emd = models.TextField(blank=True, null=True)
    msmeexemption = models.TextField(db_column='msmeExemption', blank=True, null=True)  # Field name made lowercase.
    startupexemption = models.TextField(db_column='startupExemption', blank=True, null=True)  # Field name made lowercase.
    quantity = models.TextField(blank=True, null=True)
    bidopeningdatetime = models.TextField(db_column='bidOpeningDateTime', blank=True, null=True)  # Field name made lowercase.
    bidoffervalidity = models.TextField(db_column='bidOfferValidity', blank=True, null=True)  # Field name made lowercase.
    ministrystatename = models.TextField(db_column='ministryStateName', blank=True, null=True)  # Field name made lowercase.
    departmentname = models.TextField(db_column='departmentName', blank=True, null=True)  # Field name made lowercase.
    officename = models.TextField(db_column='officeName', blank=True, null=True)  # Field name made lowercase.
    minimumaverageannualturnover = models.TextField(db_column='minimumAverageAnnualTurnover', blank=True, null=True)  # Field name made lowercase.
    yearsofpastexperience = models.TextField(db_column='yearsOfPastExperience', blank=True, null=True)  # Field name made lowercase.
    oemaverageturnover = models.TextField(db_column='oemAverageTurnover', blank=True, null=True)  # Field name made lowercase.
    contractperiod = models.TextField(db_column='contractPeriod', blank=True, null=True)  # Field name made lowercase.
    financialdocumentpricebreakuprequired = models.TextField(db_column='financialDocumentPriceBreakupRequired', blank=True, null=True)  # Field name made lowercase.
    similarcategory = models.TextField(db_column='similarCategory', blank=True, null=True)  # Field name made lowercase.
    pastexperiencesimilarservicesrequired = models.TextField(db_column='pastExperienceSimilarServicesRequired', blank=True, null=True)  # Field name made lowercase.
    documentrequiredfromseller = models.TextField(db_column='documentRequiredFromSeller', blank=True, null=True)  # Field name made lowercase.
    pastperformance = models.TextField(db_column='pastPerformance', blank=True, null=True)  # Field name made lowercase.
    bidtoraenabled = models.TextField(db_column='bidToRaEnabled', blank=True, null=True)  # Field name made lowercase.
    raqualificationrule = models.TextField(db_column='raQualificationRule', blank=True, null=True)  # Field name made lowercase.
    boqtitle = models.TextField(db_column='boqTitle', blank=True, null=True)  # Field name made lowercase.
    biddetails = models.TextField(db_column='bidDetails', blank=True, null=True)  # Field name made lowercase.
    comprehensivemaintenancechargesrequired = models.TextField(db_column='comprehensiveMaintenanceChargesRequired', blank=True, null=True)  # Field name made lowercase.
    typeofbid = models.TextField(db_column='typeOfBid', blank=True, null=True)  # Field name made lowercase.
    technicalclarificationtimeallowed = models.TextField(db_column='technicalClarificationTimeAllowed', blank=True, null=True)  # Field name made lowercase.
    inspectionrequired = models.TextField(db_column='inspectionRequired', blank=True, null=True)  # Field name made lowercase.
    estimatedbidvalue = models.TextField(db_column='estimatedBidValue', blank=True, null=True)  # Field name made lowercase.
    evaluationmethod = models.TextField(db_column='evaluationMethod', blank=True, null=True)  # Field name made lowercase.
    advisorybank = models.TextField(db_column='advisoryBank', blank=True, null=True)  # Field name made lowercase.
    epbgpercentage = models.TextField(db_column='ePbgPercentage', blank=True, null=True)  # Field name made lowercase.
    epbgdurationmonths = models.TextField(db_column='ePbgDurationMonths', blank=True, null=True)  # Field name made lowercase.
    msepurchasepreference = models.TextField(db_column='msePurchasePreference', blank=True, null=True)  # Field name made lowercase.
    miipurchasepreference = models.TextField(db_column='miiPurchasePreference', blank=True, null=True)  # Field name made lowercase.
    consigneesreportingofficer = models.TextField(db_column='consigneesReportingOfficer', blank=True, null=True)  # Field name made lowercase.
    mediationclause = models.TextField(db_column='mediationClause', blank=True, null=True)  # Field name made lowercase.
    arbitrationclause = models.TextField(db_column='arbitrationClause', blank=True, null=True)  # Field name made lowercase.
    checklist = models.TextField(blank=True, null=True)
    t247id = models.TextField(db_column='t247Id', blank=True, null=True)  # Field name made lowercase.
    scrapeddate = models.TextField(db_column='scrapedDate', blank=True, null=True)  # Field name made lowercase.
    source = models.TextField(blank=True, null=True)
    assignedto = models.TextField(db_column='assignedTo', blank=True, null=True)  # Field name made lowercase.
    markedstatus = models.TextField(db_column='markedStatus', blank=True, null=True)  # Field name made lowercase.
    sheetstatus = models.TextField(db_column='sheetStatus', blank=True, null=True)  # Field name made lowercase.
    ready = models.TextField(blank=True, null=True)
    searchkey = models.TextField(db_column='searchKey', blank=True, null=True)  # Field name made lowercase.
    downloadlink = models.TextField(db_column='downloadLink', blank=True, null=True)  # Field name made lowercase.
    currency = models.TextField(blank=True, null=True)
    excludedcategory = models.TextField(db_column='excludedCategory', blank=True, null=True)  # Field name made lowercase.
    airelevancevalid = models.BooleanField(db_column='aiRelevanceValid', blank=True, null=True)  # Field name made lowercase.
    airelevancereason = models.TextField(db_column='aiRelevanceReason', blank=True, null=True)  # Field name made lowercase.
    tenderfileurl = models.TextField(db_column='tenderFileUrl', blank=True, null=True)  # Field name made lowercase.
    parse_status = models.TextField(blank=True, null=True)
    parse_error = models.TextField(blank=True, null=True)
    itemcategory = models.TextField(db_column='itemCategory', blank=True, null=True)  # Field name made lowercase.
    totalquantity = models.TextField(db_column='totalQuantity', blank=True, null=True)  # Field name made lowercase.
    bidstatus = models.TextField(db_column='bidStatus', blank=True, null=True)  # Field name made lowercase.
    differencebetweenrank1 = models.TextField(db_column='differenceBetweenRank1', blank=True, null=True)  # Field name made lowercase.
    app = models.TextField()  # This field type is a guess.
    aps = models.TextField()  # This field type is a guess.
    apm = models.TextField()  # This field type is a guess.
    tenderstatusid = models.ForeignKey('TenderStatusTable', models.DO_NOTHING, db_column='tenderStatusId', blank=True, null=True)  # Field name made lowercase.
    state = models.TextField(blank=True, null=True)
    website = models.TextField(blank=True, null=True)
    locationcount = models.IntegerField(db_column='locationCount', blank=True, null=True)  # Field name made lowercase.
    utilitymappingid = models.ForeignKey('UtilityMappings', models.DO_NOTHING, db_column='utilityMappingId', blank=True, null=True)  # Field name made lowercase.
    createdat = models.DateTimeField(db_column='createdAt')  # Field name made lowercase.
    updatedat = models.DateTimeField(db_column='updatedAt')  # Field name made lowercase.
    attachmenturl = models.TextField(db_column='attachmentUrl', blank=True, null=True)  # Field name made lowercase.
    docketno = models.TextField(db_column='docketNo', blank=True, null=True)  # Field name made lowercase.
    remarks = models.TextField(blank=True, null=True)
    differencebetweenrank2 = models.TextField(db_column='differenceBetweenRank2', blank=True, null=True)  # Field name made lowercase.
    evaluationtabledata = models.TextField(db_column='evaluationTableData', blank=True, null=True)  # Field name made lowercase.
    nameofrank1 = models.TextField(db_column='nameOfRank1', blank=True, null=True)  # Field name made lowercase.
    nameofrank2 = models.TextField(db_column='nameOfRank2', blank=True, null=True)  # Field name made lowercase.
    valueofrank1 = models.TextField(db_column='valueOfRank1', blank=True, null=True)  # Field name made lowercase.
    valueofrank2 = models.TextField(db_column='valueOfRank2', blank=True, null=True)  # Field name made lowercase.
    result_automation_error = models.TextField(blank=True, null=True)
    result_automation_status = models.TextField(blank=True, null=True)
    size = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'gem_tenders'


class Reportings(models.Model):
    gemtenderid = models.ForeignKey(GemTenders, models.DO_NOTHING, db_column='gemTenderId', blank=True, null=True)  # Field name made lowercase.
    officer = models.TextField()
    address = models.TextField(blank=True, null=True)
    quantity = models.TextField(blank=True, null=True)
    createdat = models.DateTimeField(db_column='createdAt')  # Field name made lowercase.
    updatedat = models.DateTimeField(db_column='updatedAt')  # Field name made lowercase.
    tendermergedid = models.ForeignKey('TenderMerged', models.DO_NOTHING, db_column='tenderMergedId', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'reportings'


class TenderFiles(models.Model):
    name = models.TextField()
    extension = models.TextField()
    url = models.TextField()
    source = models.TextField()
    tags = ArrayField(models.TextField(),blank=True, null=True)  # This field type is a guess.
    tendermergedid = models.ForeignKey('TenderMerged', models.DO_NOTHING, db_column='tenderMergedId', blank=True, null=True)  # Field name made lowercase.
    createdat = models.DateTimeField(db_column='createdAt')  # Field name made lowercase.
    updatedat = models.DateTimeField(db_column='updatedAt')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'tender_files'


class TenderMerged(models.Model):
    tendertype = models.TextField(db_column='tenderType')  # Field name made lowercase. This field type is a guess.
    originalid = models.IntegerField(db_column='originalId', blank=True, null=True)  # Field name made lowercase.
    referenceno = models.TextField(db_column='referenceNo', unique=True)  # Field name made lowercase.
    tenderbrief = models.TextField(db_column='tenderBrief', blank=True, null=True)  # Field name made lowercase.
    deadline = models.DateTimeField(blank=True, null=True)
    location = models.TextField(blank=True, null=True)
    organization = models.TextField(blank=True, null=True)
    documentfees = models.TextField(db_column='documentFees', blank=True, null=True)  # Field name made lowercase.
    emd = models.TextField(blank=True, null=True)
    msmeexemption = models.TextField(db_column='msmeExemption', blank=True, null=True)  # Field name made lowercase.
    startupexemption = models.TextField(db_column='startupExemption', blank=True, null=True)  # Field name made lowercase.
    quantity = models.TextField(blank=True, null=True)
    checklist = models.TextField(blank=True, null=True)
    t247id = models.TextField(db_column='t247Id', blank=True, null=True)  # Field name made lowercase.
    scrapeddate = models.TextField(db_column='scrapedDate', blank=True, null=True)  # Field name made lowercase.
    source = models.TextField(blank=True, null=True)
    assignedto = models.TextField(db_column='assignedTo', blank=True, null=True)  # Field name made lowercase.
    markedstatus = models.TextField(db_column='markedStatus', blank=True, null=True)  # Field name made lowercase.
    sheetstatus = models.TextField(db_column='sheetStatus', blank=True, null=True)  # Field name made lowercase.
    ready = models.TextField(blank=True, null=True)
    searchkey = models.TextField(db_column='searchKey', blank=True, null=True)  # Field name made lowercase.
    downloadlink = models.TextField(db_column='downloadLink', blank=True, null=True)  # Field name made lowercase.
    currency = models.TextField(blank=True, null=True)
    excludedcategory = models.TextField(db_column='excludedCategory', blank=True, null=True)  # Field name made lowercase.
    airelevancevalid = models.BooleanField(db_column='aiRelevanceValid', blank=True, null=True)  # Field name made lowercase.
    airelevancereason = models.TextField(db_column='aiRelevanceReason', blank=True, null=True)  # Field name made lowercase.
    tenderfileurl = models.TextField(db_column='tenderFileUrl', blank=True, null=True)  # Field name made lowercase.
    docketno = models.TextField(db_column='docketNo', blank=True, null=True)  # Field name made lowercase.
    attachmenturl = models.TextField(db_column='attachmentUrl', blank=True, null=True)  # Field name made lowercase.
    remarks = models.TextField(blank=True, null=True)
    app = models.TextField()  # This field type is a guess.
    aps = models.TextField()  # This field type is a guess.
    apm = models.TextField()  # This field type is a guess.
    state = models.TextField(blank=True, null=True)
    website = models.TextField(blank=True, null=True)
    locationcount = models.IntegerField(db_column='locationCount', blank=True, null=True)  # Field name made lowercase.
    value = models.TextField(blank=True, null=True)
    bidopeningdatetime = models.TextField(db_column='bidOpeningDateTime', blank=True, null=True)  # Field name made lowercase.
    bidoffervalidity = models.TextField(db_column='bidOfferValidity', blank=True, null=True)  # Field name made lowercase.
    ministrystatename = models.TextField(db_column='ministryStateName', blank=True, null=True)  # Field name made lowercase.
    departmentname = models.TextField(db_column='departmentName', blank=True, null=True)  # Field name made lowercase.
    officename = models.TextField(db_column='officeName', blank=True, null=True)  # Field name made lowercase.
    minimumaverageannualturnover = models.TextField(db_column='minimumAverageAnnualTurnover', blank=True, null=True)  # Field name made lowercase.
    yearsofpastexperience = models.TextField(db_column='yearsOfPastExperience', blank=True, null=True)  # Field name made lowercase.
    oemaverageturnover = models.TextField(db_column='oemAverageTurnover', blank=True, null=True)  # Field name made lowercase.
    contractperiod = models.TextField(db_column='contractPeriod', blank=True, null=True)  # Field name made lowercase.
    financialdocumentpricebreakuprequired = models.TextField(db_column='financialDocumentPriceBreakupRequired', blank=True, null=True)  # Field name made lowercase.
    similarcategory = models.TextField(db_column='similarCategory', blank=True, null=True)  # Field name made lowercase.
    pastexperiencesimilarservicesrequired = models.TextField(db_column='pastExperienceSimilarServicesRequired', blank=True, null=True)  # Field name made lowercase.
    documentrequiredfromseller = models.TextField(db_column='documentRequiredFromSeller', blank=True, null=True)  # Field name made lowercase.
    pastperformance = models.TextField(db_column='pastPerformance', blank=True, null=True)  # Field name made lowercase.
    bidtoraenabled = models.TextField(db_column='bidToRaEnabled', blank=True, null=True)  # Field name made lowercase.
    raqualificationrule = models.TextField(db_column='raQualificationRule', blank=True, null=True)  # Field name made lowercase.
    boqtitle = models.TextField(db_column='boqTitle', blank=True, null=True)  # Field name made lowercase.
    biddetails = models.TextField(db_column='bidDetails', blank=True, null=True)  # Field name made lowercase.
    comprehensivemaintenancechargesrequired = models.TextField(db_column='comprehensiveMaintenanceChargesRequired', blank=True, null=True)  # Field name made lowercase.
    typeofbid = models.TextField(db_column='typeOfBid', blank=True, null=True)  # Field name made lowercase.
    technicalclarificationtimeallowed = models.TextField(db_column='technicalClarificationTimeAllowed', blank=True, null=True)  # Field name made lowercase.
    inspectionrequired = models.TextField(db_column='inspectionRequired', blank=True, null=True)  # Field name made lowercase.
    estimatedbidvalue = models.TextField(db_column='estimatedBidValue', blank=True, null=True)  # Field name made lowercase.
    evaluationmethod = models.TextField(db_column='evaluationMethod', blank=True, null=True)  # Field name made lowercase.
    advisorybank = models.TextField(db_column='advisoryBank', blank=True, null=True)  # Field name made lowercase.
    epbgpercentage = models.TextField(db_column='ePbgPercentage', blank=True, null=True)  # Field name made lowercase.
    epbgdurationmonths = models.TextField(db_column='ePbgDurationMonths', blank=True, null=True)  # Field name made lowercase.
    msepurchasepreference = models.TextField(db_column='msePurchasePreference', blank=True, null=True)  # Field name made lowercase.
    miipurchasepreference = models.TextField(db_column='miiPurchasePreference', blank=True, null=True)  # Field name made lowercase.
    consigneesreportingofficer = models.TextField(db_column='consigneesReportingOfficer', blank=True, null=True)  # Field name made lowercase.
    mediationclause = models.TextField(db_column='mediationClause', blank=True, null=True)  # Field name made lowercase.
    arbitrationclause = models.TextField(db_column='arbitrationClause', blank=True, null=True)  # Field name made lowercase.
    itemcategory = models.TextField(db_column='itemCategory', blank=True, null=True)  # Field name made lowercase.
    totalquantity = models.TextField(db_column='totalQuantity', blank=True, null=True)  # Field name made lowercase.
    bidstatus = models.TextField(db_column='bidStatus', blank=True, null=True)  # Field name made lowercase.
    differencebetweenrank1 = models.TextField(db_column='differenceBetweenRank1', blank=True, null=True)  # Field name made lowercase.
    nameofrank1 = models.TextField(db_column='nameOfRank1', blank=True, null=True)  # Field name made lowercase.
    valueofrank1 = models.TextField(db_column='valueOfRank1', blank=True, null=True)  # Field name made lowercase.
    differencebetweenrank2 = models.TextField(db_column='differenceBetweenRank2', blank=True, null=True)  # Field name made lowercase.
    nameofrank2 = models.TextField(db_column='nameOfRank2', blank=True, null=True)  # Field name made lowercase.
    valueofrank2 = models.TextField(db_column='valueOfRank2', blank=True, null=True)  # Field name made lowercase.
    evaluationtabledata = models.TextField(db_column='evaluationTableData', blank=True, null=True)  # Field name made lowercase.
    parsestatus = models.TextField(db_column='parseStatus', blank=True, null=True)  # Field name made lowercase.
    parseerror = models.TextField(db_column='parseError', blank=True, null=True)  # Field name made lowercase.
    resultautomationstatus = models.TextField(db_column='resultAutomationStatus', blank=True, null=True)  # Field name made lowercase.
    resultautomationerror = models.TextField(db_column='resultAutomationError', blank=True, null=True)  # Field name made lowercase.
    fileid = models.ForeignKey(Files, models.DO_NOTHING, db_column='fileId')  # Field name made lowercase.
    tenderstatusid = models.ForeignKey('TenderStatusTable', models.DO_NOTHING, db_column='tenderStatusId', blank=True, null=True)  # Field name made lowercase.
    utilitymappingid = models.ForeignKey('UtilityMappings', models.DO_NOTHING, db_column='utilityMappingId', blank=True, null=True)  # Field name made lowercase.
    createdat = models.DateTimeField(db_column='createdAt')  # Field name made lowercase.
    updatedat = models.DateTimeField(db_column='updatedAt')  # Field name made lowercase.
    size = models.TextField(blank=True, null=True)
    bgnoutrno = models.TextField(db_column='bgNoUtrNo', blank=True, null=True)  # Field name made lowercase.
    bidvaliditydays = models.IntegerField(db_column='bidValidityDays', blank=True, null=True)  # Field name made lowercase.
    bidvalidityexpired = models.BooleanField(db_column='bidValidityExpired', blank=True, null=True)  # Field name made lowercase.
    contractperioddays = models.IntegerField(db_column='contractPeriodDays', blank=True, null=True)  # Field name made lowercase.
    currentstatus = models.TextField(db_column='currentStatus', blank=True, null=True)  # Field name made lowercase.
    cva = models.TextField(blank=True, null=True)
    diffl1manuallyedited = models.BooleanField(db_column='diffL1ManuallyEdited', blank=True, null=True)  # Field name made lowercase.
    diffl2manuallyedited = models.BooleanField(db_column='diffL2ManuallyEdited', blank=True, null=True)  # Field name made lowercase.
    diffpercentfroml1 = models.FloatField(db_column='diffPercentFromL1', blank=True, null=True)  # Field name made lowercase.
    diffpercentfroml2 = models.FloatField(db_column='diffPercentFromL2', blank=True, null=True)  # Field name made lowercase.
    emdpaymentmode = models.TextField(db_column='emdPaymentMode', blank=True, null=True)  # Field name made lowercase.
    emdvalidity = models.DateTimeField(db_column='emdValidity', blank=True, null=True)  # Field name made lowercase.
    finalremarks = models.TextField(db_column='finalRemarks', blank=True, null=True)  # Field name made lowercase.
    loiponoanddate = models.TextField(db_column='loiPoNoAndDate', blank=True, null=True)  # Field name made lowercase.
    nextaction = models.TextField(db_column='nextAction', blank=True, null=True)  # Field name made lowercase. This field type is a guess.
    participated = models.BooleanField(blank=True, null=True)
    quotationno = models.TextField(db_column='quotationNo', blank=True, null=True)  # Field name made lowercase.
    rawmaterials = models.TextField(db_column='rawMaterials', blank=True, null=True)  # Field name made lowercase.
    reason = models.TextField(blank=True, null=True)
    reverseauctionapplicable = models.BooleanField(db_column='reverseAuctionApplicable', blank=True, null=True)  # Field name made lowercase.
    reverseauctiondate = models.DateTimeField(db_column='reverseAuctionDate', blank=True, null=True)  # Field name made lowercase.
    slno = models.IntegerField(db_column='slNo', blank=True, null=True)  # Field name made lowercase.
    tenderfor = models.TextField(db_column='tenderFor', blank=True, null=True)  # Field name made lowercase.
    tenderopeningdate = models.DateTimeField(db_column='tenderOpeningDate', blank=True, null=True)  # Field name made lowercase.
    tenderupdatestatus = models.TextField(db_column='tenderUpdateStatus', blank=True, null=True)  # Field name made lowercase. This field type is a guess.
    price = models.TextField(blank=True, null=True)  # This field type is a guess.
    proposederpitemname = models.TextField(db_column='proposedErpItemName', blank=True, null=True)  # Field name made lowercase.
    competitors = models.TextField(blank=True, null=True)
    beneficiarybankdetails = models.TextField(db_column='beneficiaryBankDetails', blank=True, null=True)  # Field name made lowercase.
    contractno = models.TextField(db_column='contractNo', blank=True, null=True)  # Field name made lowercase.
    ourrank = models.TextField(db_column='ourRank', blank=True, null=True)  # Field name made lowercase.
    ourvalue = models.TextField(db_column='ourValue', blank=True, null=True)  # Field name made lowercase.
    proposederpquantity = models.TextField(db_column='proposedErpQuantity', blank=True, null=True)  # Field name made lowercase.
    bgdate = models.TextField(db_column='bgDate', blank=True, null=True)  # Field name made lowercase.
    bgexpirydate = models.TextField(db_column='bgExpiryDate', blank=True, null=True)  # Field name made lowercase.
    bgstatus = models.TextField(db_column='bgStatus', blank=True, null=True)  # Field name made lowercase.
    claimdate = models.TextField(db_column='claimDate', blank=True, null=True)  # Field name made lowercase.
    statuscategory = models.TextField(db_column='statusCategory', blank=True, null=True)  # Field name made lowercase. This field type is a guess.
    applicableindex = models.TextField(db_column='applicableIndex', blank=True, null=True)  # Field name made lowercase.
    publisheddate = models.DateTimeField(db_column='publishedDate', blank=True, null=True)  # Field name made lowercase.
    issuingbank = models.TextField(db_column='issuingBank', blank=True, null=True)  # Field name made lowercase.
    basedate = models.DateTimeField(db_column='baseDate', blank=True, null=True)  # Field name made lowercase.
    boqsummary = models.TextField(db_column='boqSummary', blank=True, null=True)  # Field name made lowercase.
    notificationstatus = models.TextField(db_column='notificationStatus', blank=True, null=True)  # Field name made lowercase.
    cataloguedone = models.TextField(db_column='catalogueDone')  # Field name made lowercase. This field type is a guess.
    reverseauctionenddate = models.DateTimeField(db_column='reverseAuctionEndDate', blank=True, null=True)  # Field name made lowercase.
    reverseauctionstartdate = models.DateTimeField(db_column='reverseAuctionStartDate', blank=True, null=True)  # Field name made lowercase.
    reverseauctiondate = models.DateTimeField(db_column='reverseAuctionDate', blank=True, null=True)  # Field name made lowercase.
    buyerdetails = models.TextField(db_column='buyerDetails', blank=True, null=True)  # Field name made lowercase.
    inspectionagency = models.TextField(db_column='inspectionAgency', blank=True, null=True)  # Field name made lowercase.
    reverseauctionautomationstatus = models.TextField(db_column='reverseAuctionAutomationStatus', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'tender_merged'


class TenderStatusTable(models.Model):
    createdat = models.DateTimeField(db_column='createdAt')  # Field name made lowercase.
    updatedat = models.DateTimeField(db_column='updatedAt')  # Field name made lowercase.
    state = models.TextField(blank=True, null=True)
    website = models.TextField(blank=True, null=True)
    type = models.TextField()
    userid = models.TextField(db_column='userId', blank=True, null=True)  # Field name made lowercase.
    password = models.TextField(blank=True, null=True)
    mobileno = models.TextField(db_column='mobileNo', blank=True, null=True)  # Field name made lowercase.
    profilepassword = models.TextField(db_column='profilePassword', blank=True, null=True)  # Field name made lowercase.
    dscname = models.TextField(db_column='dscName', blank=True, null=True)  # Field name made lowercase.
    dscpassword = models.TextField(db_column='dscPassword', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'tender_status_table'


class UtilityMappings(models.Model):
    organization = models.TextField()
    website = models.TextField()
    createdat = models.DateTimeField(db_column='createdAt')  # Field name made lowercase.
    updatedat = models.DateTimeField(db_column='updatedAt')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'utility_mappings'