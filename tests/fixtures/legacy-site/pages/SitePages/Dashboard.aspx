<%@ Page language="C#" MasterPageFile="~masterurl/default.master" Inherits="Microsoft.SharePoint.WebPartPages.WebPartPage,Microsoft.SharePoint,Version=16.0.0.0,Culture=neutral,PublicKeyToken=71e9bce111e9429c" meta:progid="SharePoint.WebPartPage.Document" %>
<%@ Register Tagprefix="SharePoint" Namespace="Microsoft.SharePoint.WebControls" Assembly="Microsoft.SharePoint, Version=16.0.0.0, Culture=neutral, PublicKeyToken=71e9bce111e9429c" %>
<%@ Register Tagprefix="WebPartPages" Namespace="Microsoft.SharePoint.WebPartPages" Assembly="Microsoft.SharePoint, Version=16.0.0.0, Culture=neutral, PublicKeyToken=71e9bce111e9429c" %>
<asp:Content ContentPlaceHolderId="PlaceHolderPageTitle" runat="server">Procurement Dashboard</asp:Content>
<asp:Content ContentPlaceHolderId="PlaceHolderPageTitleInTitleArea" runat="server">Procurement Dashboard</asp:Content>
<asp:Content ContentPlaceHolderId="PlaceHolderAdditionalPageHead" runat="server">
	<link rel="stylesheet" type="text/css" href="/sites/procurement/SiteAssets/css/dashboard.css" />
</asp:Content>
<asp:Content ContentPlaceHolderId="PlaceHolderMain" runat="server">
	<table width="100%" cellpadding="0" cellspacing="0" style="padding: 5px 10px 10px 10px;">
		<tr>
			<td valign="top" width="70%">
				<WebPartPages:WebPartZone runat="server" Title="loc:Left" ID="Left" FrameType="TitleBarOnly"><ZoneTemplate></ZoneTemplate></WebPartPages:WebPartZone>
			</td>
			<td>&#160;</td>
			<td valign="top" width="30%">
				<WebPartPages:WebPartZone runat="server" Title="loc:Right" ID="Right" FrameType="TitleBarOnly"><ZoneTemplate></ZoneTemplate></WebPartPages:WebPartZone>
			</td>
		</tr>
	</table>
</asp:Content>
