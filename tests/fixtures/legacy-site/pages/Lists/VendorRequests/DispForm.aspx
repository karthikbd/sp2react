<%@ Page language="C#" MasterPageFile="~masterurl/default.master"    Inherits="Microsoft.SharePoint.WebPartPages.WebPartPage,Microsoft.SharePoint,Version=16.0.0.0,Culture=neutral,PublicKeyToken=71e9bce111e9429c" meta:webpartpageexpansion="full" meta:progid="SharePoint.WebPartPage.Document" %>
<%@ Register Tagprefix="SharePoint" Namespace="Microsoft.SharePoint.WebControls" Assembly="Microsoft.SharePoint, Version=16.0.0.0, Culture=neutral, PublicKeyToken=71e9bce111e9429c" %>
<%@ Register Tagprefix="Utilities" Namespace="Microsoft.SharePoint.Utilities" Assembly="Microsoft.SharePoint, Version=16.0.0.0, Culture=neutral, PublicKeyToken=71e9bce111e9429c" %>
<%@ Import Namespace="Microsoft.SharePoint" %>
<%@ Assembly Name="Microsoft.Web.CommandUI, Version=16.0.0.0, Culture=neutral, PublicKeyToken=71e9bce111e9429c" %>
<%@ Register Tagprefix="WebPartPages" Namespace="Microsoft.SharePoint.WebPartPages" Assembly="Microsoft.SharePoint, Version=16.0.0.0, Culture=neutral, PublicKeyToken=71e9bce111e9429c" %>
<asp:Content ContentPlaceHolderId="PlaceHolderPageTitle" runat="server">
	<SharePoint:ListFormPageTitle runat="server"/>
</asp:Content>
<asp:Content ContentPlaceHolderId="PlaceHolderPageTitleInTitleArea" runat="server">
	<span class="die">
		<SharePoint:ListProperty Property="LinkTitle" runat="server" id="ID_LinkTitle"/>
	</span>
</asp:Content>
<asp:Content ContentPlaceHolderId="PlaceHolderAdditionalPageHead" runat="server">
	<link rel="stylesheet" type="text/css" href="/sites/procurement/SiteAssets/css/vendor-request.css" />
</asp:Content>
<asp:Content ContentPlaceHolderId="PlaceHolderMain" runat="server">
<SharePoint:UIVersionedContent UIVersion="4" runat="server"><ContentTemplate>
<div style="padding-left:5px">
</ContentTemplate></SharePoint:UIVersionedContent>
	<table class="ms-core-tableNoSpace" id="onetIDListForm" role="presentation">
	 <tr>
	  <td>
	 <WebPartPages:WebPartZone runat="server" FrameType="None" ID="Main" Title="loc:Main"><ZoneTemplate>
<WebPartPages:ListFormWebPart runat="server" __MarkupType="xmlmarkup" WebPart="true" __WebPartId="{7B1C3E9F-2D5A-4B8C-9E7F-0A3D6C2B5E94}" >
<WebPart xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns="http://schemas.microsoft.com/WebPart/v2">
  <Title>Vendor Requests</Title>
  <FrameType>Default</FrameType>
  <Description />
  <IsIncluded>true</IsIncluded>
  <PartOrder>2</PartOrder>
  <FrameState>Normal</FrameState>
  <Height />
  <Width />
  <AllowRemove>true</AllowRemove>
  <AllowZoneChange>true</AllowZoneChange>
  <AllowMinimize>true</AllowMinimize>
  <AllowConnect>true</AllowConnect>
  <AllowEdit>true</AllowEdit>
  <AllowHide>true</AllowHide>
  <IsVisible>true</IsVisible>
  <DetailLink />
  <HelpLink />
  <HelpMode>Modeless</HelpMode>
  <Dir>Default</Dir>
  <PartImageSmall />
  <MissingAssembly>Cannot import this Web Part.</MissingAssembly>
  <PartImageLarge />
  <IsIncludedFilter />
  <ExportControlledProperties>true</ExportControlledProperties>
  <ConnectionID>00000000-0000-0000-0000-000000000000</ConnectionID>
  <ID>g_7b1c3e9f_2d5a_4b8c_9e7f_0a3d6c2b5e94</ID>
  <ListName xmlns="http://schemas.microsoft.com/WebPart/v2/ListForm">{6F1C2A10-4B7E-4D59-9A3E-0C1F7D2E8B41}</ListName>
  <ListId xmlns="http://schemas.microsoft.com/WebPart/v2/ListForm">6f1c2a10-4b7e-4d59-9a3e-0c1f7d2e8b41</ListId>
  <PageType xmlns="http://schemas.microsoft.com/WebPart/v2/ListForm">PAGE_DISPLAYFORM</PageType>
  <FormType xmlns="http://schemas.microsoft.com/WebPart/v2/ListForm">4</FormType>
  <ControlMode xmlns="http://schemas.microsoft.com/WebPart/v2/ListForm">Display</ControlMode>
  <ViewFlag xmlns="http://schemas.microsoft.com/WebPart/v2/ListForm">1048576</ViewFlag>
  <ViewFlags xmlns="http://schemas.microsoft.com/WebPart/v2/ListForm">Default</ViewFlags>
  <ListItemId xmlns="http://schemas.microsoft.com/WebPart/v2/ListForm">0</ListItemId>
  <TemplateName xmlns="http://schemas.microsoft.com/WebPart/v2/ListForm">ListForm</TemplateName>
  <CSRRenderMode xmlns="http://schemas.microsoft.com/WebPart/v2/ListForm">ServerRender</CSRRenderMode>
</WebPart>
</WebPartPages:ListFormWebPart>
<WebPartPages:ScriptEditorWebPart runat="server" ChromeType="None" Description="Allows authors to insert HTML snippets or scripts." ExportMode="All" HelpMode="Modeless" Title="Script Editor" FrameType="None" SuppressWebPartChrome="False" PartOrder="4" ID="g_3c7b9e21_5d4a_4f8e_b1c6_92a0e7d4f315" __MarkupType="vsattributemarkup" __WebPartId="{3C7B9E21-5D4A-4F8E-B1C6-92A0E7D4F315}" WebPart="true" __designer:IsClosed="false" Content="&lt;script type=&quot;text/javascript&quot; src=&quot;/sites/procurement/SiteAssets/js/jquery-1.12.4.min.js&quot;&gt;&lt;/script&gt;
&lt;div id=&quot;vr-banner&quot; class=&quot;vr-banner&quot; style=&quot;display:none&quot;&gt;&lt;/div&gt;
&lt;script type=&quot;text/javascript&quot;&gt;
$(function () {
    function rowFor(label) {
        return $(&quot;h3.ms-standardheader&quot;).filter(function () {
            return $.trim($(this).text()) === label;
        }).closest(&quot;tr&quot;);
    }
    var result = $.trim(rowFor(&quot;Screening Result&quot;).find(&quot;td.ms-formbody&quot;).text());
    if (result === &quot;Confirmed Match&quot;) {
        $(&quot;#vr-banner&quot;).text(&quot;This vendor has a confirmed sanctions match. Do not issue a purchase order.&quot;).show();
    }
    var justification = rowFor(&quot;High Risk Justification&quot;);
    if ($.trim(justification.find(&quot;td.ms-formbody&quot;).text()) === &quot;&quot;) {
        justification.hide();
    }
});
&lt;/script&gt;"></WebPartPages:ScriptEditorWebPart>
</ZoneTemplate></WebPartPages:WebPartZone>
	  </td>
	 </tr>
	</table>
<SharePoint:UIVersionedContent UIVersion="4" runat="server"><ContentTemplate>
</div>
</ContentTemplate></SharePoint:UIVersionedContent>
</asp:Content>
<asp:Content ContentPlaceHolderId="PlaceHolderTitleLeftBorder" runat="server">
<table cellpadding="0" height="100%" width="100%" cellspacing="0">
 <tr><td class="ms-areaseparatorleft"><img src="/_layouts/15/images/blank.gif?rev=44" width='1' height='1' alt="" /></td></tr>
</table>
</asp:Content>
<asp:Content ContentPlaceHolderId="PlaceHolderBodyAreaClass" runat="server">
<SharePoint:StyleBlock runat="server">
.ms-bodyareaframe {
	padding: 8px;
	border: none;
}
</SharePoint:StyleBlock>
</asp:Content>
