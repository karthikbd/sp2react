/*
 * Vendor Requests - NewForm.aspx / EditForm.aspx customisations
 * Loaded from the Script Editor web part on both forms.
 * Requires jQuery 1.12.4 and jquery.SPServices-2014.02
 * Last change: R. Patel 2019-03-11 (added sanctions screening + compliance alerts)
 */
var VR = VR || {};

VR.siteUrl = _spPageContextInfo.webServerRelativeUrl;
VR.isNew = window.location.pathname.toLowerCase().indexOf("newform.aspx") > -1;
VR.isEdit = window.location.pathname.toLowerCase().indexOf("editform.aspx") > -1;
VR.isReviewer = false;
VR.duplicateId = null;
VR.originalScreening = "";

// Find the form row for a column by its display name (label text without the required asterisk)
VR.getFieldRow = function (displayName) {
    return $("nobr").filter(function () {
        return $.trim($(this).text().replace(/\s*\*$/, "")) === displayName;
    }).closest("tr");
};

// Disable every input in a row; people pickers are made read-only
VR.lockField = function (displayName) {
    var row = VR.getFieldRow(displayName);
    row.find("input, select, textarea").prop("disabled", true);
    row.find("div[contenteditable='true']").attr("contenteditable", "false");
    row.find("a[title='Browse']").hide();
};

VR.pickerIsEmpty = function (displayName) {
    var row = VR.getFieldRow(displayName);
    return $.trim(row.find("div.ms-inputuserfield").text()) === "" &&
        row.find("span.ms-entity-resolved").length === 0;
};

VR.parseDate = function (value) {
    if (!value) { return null; }
    var p = value.split("/");
    return new Date(parseInt(p[2], 10), parseInt(p[0], 10) - 1, parseInt(p[1], 10));
};

// Country -> Risk Rating (GET from the Countries list)
VR.loadRisk = function () {
    var countryId = $("select[title='Country Required Field']").val();
    if (!countryId || countryId === "0") {
        $("input[title='Risk Rating']").val("");
        VR.toggleJustification("");
        return;
    }
    $.ajax({
        url: VR.siteUrl + "/_api/web/lists/getbytitle('Countries')/items(" + countryId + ")?$select=RiskLevel",
        type: "GET",
        headers: { "Accept": "application/json;odata=verbose" },
        success: function (data) {
            $("input[title='Risk Rating']").val(data.d.RiskLevel);
            VR.toggleJustification(data.d.RiskLevel);
        }
    });
};

VR.toggleJustification = function (riskLevel) {
    VR.getFieldRow("High Risk Justification").toggle(riskLevel === "High");
};

VR.toggleScreening = function () {
    var screened = $("input[title='Sanctions Screened']").is(":checked");
    VR.getFieldRow("Screening Result").toggle(screened);
    if (!screened) {
        $("select[title='Screening Result']").val("");
    }
};

// Duplicate Tax ID check (GET from this list, excluding the current item)
VR.checkDuplicateTaxId = function () {
    var taxId = $.trim($("input[title='Tax ID']").val());
    $(".vr-dup").remove();
    VR.duplicateId = null;
    if (taxId === "") { return; }
    var currentId = VR.isEdit ? GetUrlKeyValue("ID") : 0;
    $.ajax({
        url: VR.siteUrl + "/_api/web/lists/getbytitle('Vendor Requests')/items?$select=ID&$filter=TaxID eq '" + taxId + "' and ID ne " + currentId,
        type: "GET",
        headers: { "Accept": "application/json;odata=verbose" },
        success: function (data) {
            if (data.d.results.length > 0) {
                VR.duplicateId = data.d.results[0].ID;
                $("input[title='Tax ID']").after("<span class='ms-formvalidation vr-dup'><br/>A vendor request with this Tax ID already exists (ID " + VR.duplicateId + ").</span>");
            }
        }
    });
};

// POST a Compliance Alerts item when a confirmed sanctions match is recorded
VR.raiseComplianceAlert = function () {
    var vendorName = $("input[title='Vendor Name Required Field']").val();
    var country = $("select[title='Country Required Field'] option:selected").text();
    $.ajax({
        url: VR.siteUrl + "/_api/web/lists/getbytitle('Compliance Alerts')/items",
        type: "POST",
        async: false,
        contentType: "application/json;odata=verbose",
        headers: {
            "Accept": "application/json;odata=verbose",
            "X-RequestDigest": $("#__REQUESTDIGEST").val()
        },
        data: JSON.stringify({
            "__metadata": { "type": "SP.Data.ComplianceAlertsListItem" },
            "Title": "Confirmed sanctions match: " + vendorName,
            "VendorRequestId": parseInt(GetUrlKeyValue("ID"), 10),
            "Country": country
        })
    });
};

$(document).ready(function () {
    // Is the current user a compliance reviewer?
    $().SPServices({
        operation: "GetGroupCollectionFromUser",
        userLoginName: $().SPServices.SPGetCurrentUser(),
        async: false,
        completefunc: function (xData, Status) {
            VR.isReviewer = $(xData.responseXML).find("Group[Name='Compliance Reviewers']").length === 1;
        }
    });

    // Department -> Cost Center cascade
    $().SPServices.SPCascadeDropdowns({
        relationshipList: "Cost Centers",
        relationshipListParentColumn: "Department",
        relationshipListChildColumn: "Title",
        parentColumn: "Department",
        childColumn: "Cost Center",
        debug: false
    });

    if (VR.isNew) {
        // Requester defaults to the current user
        $().SPServices.SPFindPeoplePicker({
            peoplePickerDisplayName: "Requester",
            valueToSet: $().SPServices.SPGetCurrentUser(),
            checkNames: true
        });
        // Status is set on save, not by the requester
        VR.getFieldRow("Status").hide();
        VR.getFieldRow("Reviewer Comments").hide();
    }

    VR.lockField("Requester");
    VR.lockField("Risk Rating");

    $("select[title='Country Required Field']").change(VR.loadRisk);
    VR.loadRisk();

    $("input[title='Sanctions Screened']").change(VR.toggleScreening);
    VR.toggleScreening();

    $("input[title='Tax ID']").blur(VR.checkDuplicateTaxId);

    if (VR.isEdit) {
        var status = $("select[title='Status Required Field']").val();
        VR.originalScreening = $("select[title='Screening Result']").val();
        if ((status === "Approved" || status === "Rejected") && !VR.isReviewer) {
            alert("This request has been " + status.toLowerCase() + " and can no longer be edited.");
            window.location.href = "DispForm.aspx?ID=" + GetUrlKeyValue("ID") + "&Source=" + encodeURIComponent(GetUrlKeyValue("Source"));
            return;
        }
        if (!VR.isReviewer) {
            VR.lockField("Status");
            VR.getFieldRow("Reviewer Comments").hide();
        }
    }
});

// Called by SharePoint before the item is saved; returning false cancels the save
function PreSaveAction() {
    if (VR.duplicateId) {
        alert("A vendor request with this Tax ID already exists (ID " + VR.duplicateId + ").");
        return false;
    }
    if ($("input[title='Risk Rating']").val() === "High" &&
        $.trim($("textarea[title='High Risk Justification']").val()) === "") {
        alert("High Risk Justification is required for vendors in high-risk countries.");
        return false;
    }
    var contractValue = parseFloat($("input[title='Contract Value Required Field']").val().replace(/[$,]/g, "")) || 0;
    if (contractValue > 100000 && VR.pickerIsEmpty("Second Approver")) {
        alert("A Second Approver is required for contracts over $100,000.");
        return false;
    }
    if ($("input[title='Sanctions Screened']").is(":checked") && $("select[title='Screening Result']").val() === "") {
        alert("Select a Screening Result when Sanctions Screened is checked.");
        return false;
    }
    var requestDate = VR.parseDate($("input[title='Request Date Required Field']").val());
    var startDate = VR.parseDate($("input[title='Expected Start Date']").val());
    if (requestDate && startDate && startDate < requestDate) {
        alert("Expected Start Date cannot be before the Request Date.");
        return false;
    }
    if (VR.isEdit && $("select[title='Status Required Field']").val() === "Rejected" &&
        $.trim($("textarea[title='Reviewer Comments']").val()) === "") {
        alert("Please enter reviewer comments when rejecting a request.");
        return false;
    }
    if (VR.isNew) {
        $("select[title='Status Required Field']").val("Submitted");
    }
    if (VR.isEdit && $("select[title='Screening Result']").val() === "Confirmed Match" &&
        VR.originalScreening !== "Confirmed Match") {
        VR.raiseComplianceAlert();
    }
    return true;
}
