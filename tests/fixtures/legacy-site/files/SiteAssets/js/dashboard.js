/*
 * Procurement dashboard (SitePages/Dashboard.aspx)
 * Status tiles, "My requests", reviewer queue with quick approve, latest compliance alerts.
 * Requires jQuery 1.12.4 and jquery.SPServices-2014.02
 */
var DB = DB || {};
DB.siteUrl = _spPageContextInfo.webServerRelativeUrl;
DB.listUrl = DB.siteUrl + "/_api/web/lists/getbytitle('Vendor Requests')";
DB.statuses = ["Submitted", "Under Review", "Approved", "Rejected"];

DB.get = function (url) {
    return $.ajax({ url: url, type: "GET", headers: { "Accept": "application/json;odata=verbose" } });
};

DB.loadTiles = function () {
    $.each(DB.statuses, function (i, status) {
        DB.get(DB.listUrl + "/items?$select=ID&$filter=Status eq '" + status + "'&$top=5000").done(function (data) {
            $("#db-tile-" + i + " .db-count").text(data.d.results.length);
        });
    });
    DB.get(DB.listUrl + "/items?$select=ID&$filter=RiskRating eq 'High' and Status ne 'Approved' and Status ne 'Rejected'&$top=5000").done(function (data) {
        $("#db-highrisk .db-count").text(data.d.results.length);
        $("#db-highrisk").toggleClass("db-alert", data.d.results.length > 0);
    });
};

DB.loadMyRequests = function () {
    var url = DB.listUrl + "/items?$select=ID,Title,Status,ContractValue,Modified,Country/Title&$expand=Country" +
        "&$filter=AuthorId eq " + _spPageContextInfo.userId + "&$orderby=Modified desc&$top=10";
    DB.get(url).done(function (data) {
        var rows = $.map(data.d.results, function (item) {
            return "<tr><td><a href='" + DB.siteUrl + "/Lists/VendorRequests/DispForm.aspx?ID=" + item.ID +
                "&Source=" + encodeURIComponent(window.location.href) + "'>" + item.Title + "</a></td>" +
                "<td>" + item.Country.Title + "</td><td>" + item.Status + "</td>" +
                "<td class='db-num'>$" + Number(item.ContractValue).toLocaleString("en-US", { minimumFractionDigits: 2 }) + "</td></tr>";
        });
        $("#db-my tbody").html(rows.length ? rows.join("") : "<tr><td colspan='4'>You have no vendor requests.</td></tr>");
    });
};

DB.loadQueue = function () {
    var url = DB.listUrl + "/items?$select=ID,Title,RiskRating,ScreeningResult,ContractValue,Requester/Title&$expand=Requester" +
        "&$filter=Status eq 'Submitted' or Status eq 'Under Review'&$orderby=Created asc&$top=50";
    DB.get(url).done(function (data) {
        var rows = $.map(data.d.results, function (item) {
            var approve = item.ScreeningResult === "Clear" ?
                "<button type='button' class='db-approve' data-id='" + item.ID + "'>Approve</button>" : "";
            return "<tr><td><a href='" + DB.siteUrl + "/Lists/VendorRequests/EditForm.aspx?ID=" + item.ID + "'>" + item.Title + "</a></td>" +
                "<td>" + item.Requester.Title + "</td><td>" + (item.RiskRating || "") + "</td>" +
                "<td>" + (item.ScreeningResult || "Not screened") + "</td><td>" + approve + "</td></tr>";
        });
        $("#db-queue tbody").html(rows.length ? rows.join("") : "<tr><td colspan='5'>Nothing is waiting for review.</td></tr>");
    });
};

// Quick approve: MERGE Status on the item (PUT-style update with etag)
DB.approve = function (id) {
    if (!confirm("Approve this vendor request?")) { return; }
    DB.get(DB.listUrl + "/items(" + id + ")?$select=ID").done(function (data) {
        $.ajax({
            url: DB.listUrl + "/items(" + id + ")",
            type: "POST",
            contentType: "application/json;odata=verbose",
            headers: {
                "Accept": "application/json;odata=verbose",
                "X-RequestDigest": $("#__REQUESTDIGEST").val(),
                "X-HTTP-Method": "MERGE",
                "IF-MATCH": data.d.__metadata.etag
            },
            data: JSON.stringify({ "__metadata": { "type": "SP.Data.VendorRequestsListItem" }, "Status": "Approved" }),
            success: function () { DB.loadQueue(); DB.loadTiles(); },
            error: function (xhr) {
                alert(xhr.status === 412 ? "This request was changed by someone else. Refresh and try again." : "The request could not be approved.");
            }
        });
    });
};

DB.loadAlerts = function () {
    $().SPServices({
        operation: "GetListItems",
        listName: "Compliance Alerts",
        CAMLViewFields: "<ViewFields><FieldRef Name='Title' /><FieldRef Name='Country' /><FieldRef Name='Created' /></ViewFields>",
        CAMLQuery: "<Query><OrderBy><FieldRef Name='Created' Ascending='FALSE' /></OrderBy></Query>",
        CAMLRowLimit: 5,
        completefunc: function (xData, Status) {
            var items = $(xData.responseXML).SPFilterNode("z:row");
            var html = items.map(function () {
                return "<li>" + $(this).attr("ows_Title") + " <span class='db-muted'>(" + $(this).attr("ows_Country") + ")</span></li>";
            }).get().join("");
            $("#db-alerts").html(html || "<li>No compliance alerts.</li>");
        }
    });
};

$(document).ready(function () {
    DB.loadTiles();
    DB.loadMyRequests();
    $().SPServices({
        operation: "GetGroupCollectionFromUser",
        userLoginName: $().SPServices.SPGetCurrentUser(),
        async: true,
        completefunc: function (xData) {
            if ($(xData.responseXML).find("Group[Name='Compliance Reviewers']").length === 1) {
                $("#db-queue-panel").show();
                DB.loadQueue();
            }
        }
    });
    DB.loadAlerts();
    $("#db-queue").on("click", ".db-approve", function () { DB.approve($(this).data("id")); });
});
