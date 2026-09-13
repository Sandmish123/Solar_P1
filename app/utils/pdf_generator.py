import os
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from app.models.solar_project import SolarProject
import json


def generate_project_pdf(project: SolarProject, output_path: str):
    """Generates a dynamic PDF based on actual DB calculations tying closely to the PDF visual layout."""
    
    doc = SimpleDocTemplate(output_path, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    
    # Custom Styles matching UI closely
    title_style = ParagraphStyle(
        name='TitleStyle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=20,
        fontName='Helvetica-Bold'
    )
    
    subtitle_style = ParagraphStyle(
        name='SubTitleStyle',
        parent=styles['Normal'],
        fontSize=12,
        textColor=colors.gray,
        spaceAfter=30
    )
    
    h2_style = ParagraphStyle(
        name='H2Style',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=15,
        fontName='Helvetica-Bold'
    )
    
    normal_style = styles['Normal']
    
    story = []
    
    # --- PAGE 1: COVER/OVERVIEW ---
    story.append(Paragraph(f"{project.capacity_kwp}kWp Ongrid proposal", subtitle_style))
    story.append(Paragraph("SOLAR ENERGY PROPOSAL", title_style))
    story.append(Spacer(1, 4*inch))
    
    # Project Details Table
    details_data = [
        ['Project Name', project.project_name],
        ['Client Name', project.client_name],
        ['Site Address', project.site_address],
        ['System Size', f"{project.capacity_kwp} kWp"],
        ['Panels', f"{project.num_panels} × {project.panel_wattage}W"],
        ['Date', project.date]
    ]
    
    details_table = Table(details_data, colWidths=[2*inch, 4*inch])
    details_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f6fa')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2c3e50')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dcdde1')),
    ]))
    
    story.append(details_table)
    story.append(PageBreak())
    
    # --- PAGE 2: ENERGY REPORT ---
    story.append(Paragraph("ENERGY REPORT", title_style))
    story.append(Paragraph("ANNUAL GENERATION", h2_style))
    
    gen_data = [
        [f"{round(project.annual_gen_kwh / 1000, 1)} MWh", ''],
        [f"Specific Yield: {project.specific_yield} kWh/kWp", f"Performance Ratio: {round(project.performance_ratio, 1)}%"]
    ]
    
    gen_table = Table(gen_data, colWidths=[3.5*inch, 3*inch])
    gen_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#1f4e5a')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (0, 0), 30),
        ('FONTSIZE', (0, 1), (1, 1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
        ('TOPPADDING', (0, 0), (-1, -1), 15),
    ]))
    story.append(gen_table)
    story.append(Spacer(1, 30))
    
    # Losses Breakdown
    story.append(Paragraph("LOSSES BREAKDOWN", h2_style))
    losses_data = [
        ['Temperature', f"{project.temp_loss_pct}%"],
        ['Shading', f"{project.shading_loss_pct}%"],
        ['Soiling', f"{project.soiling_loss_pct}%"],
        ['Inverter', f"{project.inverter_loss_pct}%"],
        ['Mismatch', f"{project.mismatch_loss_pct}%"],
        ['DC Wiring', f"{project.dc_wiring_loss_pct}%"],
        ['AC Wiring', f"{project.ac_wiring_loss_pct}%"],
        ['Total System Loss', f"{round(project.total_system_loss, 1)}%"]
    ]
    
    losses_table = Table(losses_data, colWidths=[5*inch, 1.5*inch])
    losses_table_style = TableStyle([
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, -1), (1, -1), 'Helvetica-Bold'),
        ('LINEABOVE', (0, -1), (1, -1), 1, colors.gray),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ])
    losses_table.setStyle(losses_table_style)
    story.append(losses_table)
    story.append(Spacer(1, 30))
    
    # System Summary
    story.append(Paragraph("SYSTEM SUMMARY", h2_style))
    summary_data = [
        ['Capacity', 'Panels', 'Roof Area'],
        [f"{project.capacity_kwp} kWp", f"{project.num_panels} ({project.panel_wattage}W)", f"{project.roof_area_sqm} m²"]
    ]
    summary_table = Table(summary_data, colWidths=[2*inch, 2.5*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica'),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, 1), 16),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#008080')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('BOX', (0, 0), (0, -1), 1, colors.lightgrey),
        ('BOX', (1, 0), (1, -1), 1, colors.lightgrey),
        ('BOX', (2, 0), (2, -1), 1, colors.lightgrey),
    ]))
    story.append(summary_table)
    
    try:
        doc.build(story)
        return True
    except Exception as e:
        print(f"Error generating PDF: {e}")
        return False
