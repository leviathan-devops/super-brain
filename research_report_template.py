"""
ResearchBriefing - Intelligence Briefing Template using ReportLab
Professional research report generator with military-style formatting
"""

import os
import requests
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, white, grey
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image
from reportlab.platypus import KeepTogether
from reportlab.pdfgen import canvas
from reportlab.lib import colors

# Color Palette
MIDNIGHT_NAVY = HexColor('#0A1929')
DEEP_OCEAN_BLUE = HexColor('#1E3A5F')
CYAN_GLOW = HexColor('#00B4D8')
ALERT_ORANGE = HexColor('#FF6B35')
OFF_WHITE = HexColor('#F8F9FA')
BODY_TEXT = HexColor('#212529')
HEADER_TEXT = HexColor('#0A1929')

class ResearchBriefing:
    """Intelligence Briefing report generator using ReportLab"""

    def __init__(self, title, report_type, date, briefing_agent):
        """
        Initialize the research briefing.

        Args:
            title: Report title
            report_type: Type of briefing (e.g., "STRATEGIC ANALYSIS")
            date: Report date (string or datetime)
            briefing_agent: Name of briefing agent/analyst
        """
        self.title = title
        self.report_type = report_type
        self.date = date if isinstance(date, str) else date.strftime('%Y-%m-%d')
        self.briefing_agent = briefing_agent
        self.story = []
        self.page_count = 0

    def add_cover_page(self):
        """Add a professional cover page"""
        # Create a custom cover page by adding a spacer and title section
        spacer = Spacer(1*inch, 1.5*inch)
        self.story.append(spacer)

        # Classification stamp
        classification_style = ParagraphStyle(
            'Classification',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=14,
            textColor=ALERT_ORANGE,
            spaceAfter=0.3*inch,
            alignment=1,  # center
            fontName='Helvetica-Bold'
        )
        self.story.append(Paragraph('⊟ INTELLIGENCE BRIEFING ⊟', classification_style))

        # Title
        title_style = ParagraphStyle(
            'CoverTitle',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=28,
            textColor=white,
            spaceAfter=0.3*inch,
            alignment=1,
            fontName='Helvetica-Bold'
        )
        self.story.append(Paragraph(self.title, title_style))

        # Report type
        type_style = ParagraphStyle(
            'ReportType',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=16,
            textColor=CYAN_GLOW,
            spaceAfter=1*inch,
            alignment=1,
            fontName='Helvetica'
        )
        self.story.append(Paragraph(self.report_type, type_style))

        # Metadata
        meta_style = ParagraphStyle(
            'Metadata',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=11,
            textColor=BODY_TEXT,
            spaceAfter=0.2*inch,
            alignment=1,
            fontName='Helvetica'
        )
        self.story.append(Paragraph(f"Date: {self.date}", meta_style))
        self.story.append(Paragraph(f"Analyst: {self.briefing_agent}", meta_style))
        self.story.append(Spacer(1*inch, 0.5*inch))
        self.story.append(Paragraph("INTERNAL USE ONLY", meta_style))

        self.story.append(PageBreak())

    def add_executive_summary(self, key_findings, recommendations, impact):
        """
        Add executive summary section.

        Args:
            key_findings: List of key findings
            recommendations: List of recommendations
            impact: Impact assessment text
        """
        # Section header
        self._add_section_header('EXECUTIVE SUMMARY')

        # Key Findings
        finding_title = ParagraphStyle(
            'FindingTitle',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=12,
            textColor=HEADER_TEXT,
            spaceAfter=0.15*inch,
            fontName='Helvetica-Bold'
        )
        self.story.append(Paragraph('KEY FINDINGS', finding_title))

        for idx, finding in enumerate(key_findings, 1):
            bullet_style = ParagraphStyle(
                f'Finding{idx}',
                parent=getSampleStyleSheet()['Normal'],
                fontSize=11,
                textColor=BODY_TEXT,
                spaceAfter=0.1*inch,
                leftIndent=0.3*inch,
                fontName='Helvetica'
            )
            # Highlight with orange marker
            marked_finding = f"<font color='#FF6B35'><b>[KEY]</b></font> {finding}"
            self.story.append(Paragraph(marked_finding, bullet_style))

        self.story.append(Spacer(1*inch, 0.2*inch))

        # Recommendations
        self.story.append(Paragraph('RECOMMENDATIONS', finding_title))
        for idx, rec in enumerate(recommendations, 1):
            bullet_style = ParagraphStyle(
                f'Rec{idx}',
                parent=getSampleStyleSheet()['Normal'],
                fontSize=11,
                textColor=BODY_TEXT,
                spaceAfter=0.1*inch,
                leftIndent=0.3*inch,
                fontName='Helvetica'
            )
            self.story.append(Paragraph(f"• {rec}", bullet_style))

        self.story.append(Spacer(1*inch, 0.2*inch))

        # Impact
        self.story.append(Paragraph('IMPACT ASSESSMENT', finding_title))
        impact_style = ParagraphStyle(
            'Impact',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=11,
            textColor=BODY_TEXT,
            spaceAfter=0.3*inch,
            alignment=4,  # justify
            fontName='Helvetica'
        )
        self.story.append(Paragraph(impact, impact_style))
        self.story.append(PageBreak())

    def add_section(self, title, content):
        """
        Add a standard section with paragraphs.

        Args:
            title: Section title
            content: List of paragraph strings
        """
        self._add_section_header(title)

        para_style = ParagraphStyle(
            'BodyParagraph',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=11,
            textColor=BODY_TEXT,
            spaceAfter=0.15*inch,
            alignment=4,  # justify
            fontName='Helvetica'
        )

        for paragraph_text in content:
            self.story.append(Paragraph(paragraph_text, para_style))

        self.story.append(Spacer(1*inch, 0.2*inch))

    def add_intelligence_section(self, title, subsections):
        """
        Add an intelligence section with subsections.

        Args:
            title: Section title
            subsections: List of (subtitle, content) tuples
        """
        self._add_section_header(title)

        for subtitle, content in subsections:
            subsection_style = ParagraphStyle(
                'Subsection',
                parent=getSampleStyleSheet()['Normal'],
                fontSize=12,
                textColor=DEEP_OCEAN_BLUE,
                spaceAfter=0.1*inch,
                fontName='Helvetica-Bold'
            )
            self.story.append(Paragraph(subtitle, subsection_style))

            para_style = ParagraphStyle(
                'SubContent',
                parent=getSampleStyleSheet()['Normal'],
                fontSize=10,
                textColor=BODY_TEXT,
                spaceAfter=0.1*inch,
                leftIndent=0.2*inch,
                alignment=4,
                fontName='Helvetica'
            )
            self.story.append(Paragraph(content, para_style))

        self.story.append(Spacer(1*inch, 0.2*inch))

    def add_table(self, headers, data):
        """
        Add a professional cyan-accented table.

        Args:
            headers: List of header strings
            data: List of lists containing table data
        """
        self.story.append(Spacer(1*inch, 0.15*inch))

        # Build table data with headers
        table_data = [headers] + data

        # Create table
        col_widths = [letter[0] / len(headers) - 0.5*inch / len(headers)] * len(headers)
        table = Table(table_data, colWidths=col_widths)

        # Style the table
        table.setStyle(TableStyle([
            # Header row styling
            ('BACKGROUND', (0, 0), (-1, 0), CYAN_GLOW),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),

            # Data rows
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 1), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),

            # Alternating row colors
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#F0F7FC')]),

            # Borders
            ('GRID', (0, 0), (-1, -1), 1, HexColor('#CCCCCC')),
            ('LINEABOVE', (0, 0), (-1, 0), 2, CYAN_GLOW),
        ]))

        self.story.append(table)
        self.story.append(Spacer(1*inch, 0.2*inch))

    def add_callout(self, text, severity='info'):
        """
        Add a callout box.

        Args:
            text: Callout text
            severity: 'info' (cyan), 'alert' (orange), or 'critical' (red)
        """
        # Determine colors based on severity
        if severity == 'alert':
            bg_color = HexColor('#FEF1E8')
            border_color = ALERT_ORANGE
        elif severity == 'critical':
            bg_color = HexColor('#FFE8E8')
            border_color = HexColor('#DC143C')
        else:  # info
            bg_color = HexColor('#E8F4F8')
            border_color = CYAN_GLOW

        callout_style = ParagraphStyle(
            'Callout',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=11,
            textColor=BODY_TEXT,
            fontName='Helvetica',
            leftIndent=0.2*inch,
            rightIndent=0.2*inch
        )

        # Create a table to simulate the callout box with left border
        callout_data = [[Paragraph(text, callout_style)]]
        callout_table = Table(callout_data, colWidths=[letter[0] - 1*inch])
        callout_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), bg_color),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('BORDER', (0, 0), (-1, -1), 1, border_color),
            ('LEFTPADDING', (0, 0), (0, -1), 0),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))

        self.story.append(callout_table)
        self.story.append(Spacer(1*inch, 0.15*inch))

    def add_recommendation(self, number, text, timeline):
        """
        Add a numbered recommendation.

        Args:
            number: Recommendation number
            text: Recommendation text
            timeline: Timeline for implementation
        """
        rec_style = ParagraphStyle(
            'Recommendation',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=11,
            textColor=BODY_TEXT,
            fontName='Helvetica-Bold',
            spaceAfter=0.05*inch
        )

        timeline_style = ParagraphStyle(
            'Timeline',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=10,
            textColor=HexColor('#666666'),
            fontName='Helvetica-Oblique',
            spaceAfter=0.1*inch,
            leftIndent=0.3*inch
        )

        # Recommendation number with cyan accent
        rec_text = f"<b>{number}.</b> {text}"
        self.story.append(Paragraph(rec_text, rec_style))
        self.story.append(Paragraph(f"Timeline: {timeline}", timeline_style))

    def add_appendix(self, title, content):
        """
        Add an appendix section.

        Args:
            title: Appendix title
            content: Appendix content (string or list of strings)
        """
        self._add_section_header(title)

        if isinstance(content, list):
            for item in content:
                appendix_style = ParagraphStyle(
                    'AppendixText',
                    parent=getSampleStyleSheet()['Normal'],
                    fontSize=10,
                    textColor=BODY_TEXT,
                    spaceAfter=0.1*inch,
                    fontName='Courier'
                )
                self.story.append(Paragraph(item, appendix_style))
        else:
            appendix_style = ParagraphStyle(
                'AppendixText',
                parent=getSampleStyleSheet()['Normal'],
                fontSize=10,
                textColor=BODY_TEXT,
                spaceAfter=0.1*inch,
                fontName='Courier'
            )
            self.story.append(Paragraph(content, appendix_style))

    def _add_section_header(self, title):
        """Internal method to add a styled section header"""
        header_para = Paragraph(title, ParagraphStyle(
            'SectionHeader',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=14,
            textColor=white,
            fontName='Helvetica-Bold',
            spaceAfter=0.15*inch,
            spaceBefore=0.1*inch,
        ))

        # Create a table for gradient-like header bar
        header_table = Table([[header_para]], colWidths=[letter[0] - 1*inch])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), MIDNIGHT_NAVY),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('BORDER', (0, 0), (-1, -1), 0),
        ]))

        self.story.append(header_table)
        self.story.append(Spacer(1*inch, 0.1*inch))

    def generate(self, output_path):
        """
        Generate the PDF report.

        Args:
            output_path: Output file path for the PDF
        """
        # Ensure output directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Create PDF
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=0.5*inch,
            leftMargin=0.5*inch,
            topMargin=0.5*inch,
            bottomMargin=0.75*inch
        )

        # Add cover page
        self.add_cover_page()

        # Build PDF with custom page numbering
        doc.build(self.story, onFirstPage=self._add_page_footer, onLaterPages=self._add_page_footer)

        return output_path

    def _add_page_footer(self, canvas_obj, doc):
        """Add footer to each page"""
        canvas_obj.saveState()

        # Footer text
        footer_style = ParagraphStyle(
            'Footer',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=9,
            textColor=BODY_TEXT,
            fontName='Courier'
        )

        # Get current page number (approximate)
        page_num_text = f"PAGE {doc.page} OF [TOTAL] | LEVIATHAN INTELLIGENCE — INTERNAL USE ONLY"

        canvas_obj.setFont('Courier', 9)
        canvas_obj.setFillColor(BODY_TEXT)
        canvas_obj.drawString(0.5*inch, 0.3*inch, page_num_text)

        canvas_obj.restoreState()


def deliver_to_discord(pdf_path, channel_id, bot_token):
    """
    Upload a PDF to Discord using a bot token.

    Args:
        pdf_path: Path to the PDF file
        channel_id: Discord channel ID
        bot_token: Discord bot token

    Returns:
        HTTP status code
    """
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {bot_token}"}

    try:
        with open(pdf_path, 'rb') as f:
            files = {"file": (os.path.basename(pdf_path), f, "application/pdf")}
            data = {"content": f"📋 **RESEARCH BRIEFING DELIVERED**\n{os.path.basename(pdf_path)}"}
            response = requests.post(url, headers=headers, files=files, data=data)
        return response.status_code
    except Exception as e:
        print(f"Error delivering to Discord: {e}")
        return None


# =============================================================================
# DEMO / TEST
# =============================================================================

if __name__ == '__main__':
    print("=" * 80)
    print("RESEARCH BRIEFING TEMPLATE - DEMO")
    print("=" * 80)

    # Create sample briefing
    briefing = ResearchBriefing(
        title="Emerging AI Threats: Q1 2026 Assessment",
        report_type="STRATEGIC ANALYSIS - THREAT ASSESSMENT",
        date="2026-03-02",
        briefing_agent="Dr. Elena Vasquez, Intelligence Division"
    )

    # Executive Summary
    briefing.add_executive_summary(
        key_findings=[
            "Autonomous systems capability has advanced 40% beyond baseline projections",
            "Cross-border data exfiltration attempts increased 280% in past quarter",
            "Three new threat actors identified with nation-state-level resources"
        ],
        recommendations=[
            "Implement enhanced monitoring protocols for autonomous system communications",
            "Establish rapid-response teams for cross-border incident handling",
            "Coordinate international intelligence sharing on identified threat actors"
        ],
        impact="High risk of strategic surprise if countermeasures not deployed within 90 days. Recommend immediate escalation to strategic planning committee."
    )

    # Background Section
    briefing.add_section(
        title="BACKGROUND & CONTEXT",
        content=[
            "The technological landscape has shifted dramatically over the past eighteen months. Advanced artificial intelligence systems, once confined to research laboratories and corporate environments, are now proliferating across critical infrastructure domains. This briefing synthesizes recent threat intelligence and technical assessments to provide strategic-level decision makers with actionable intelligence.",
            "Our analysis draws from multiple sources: network telemetry, disclosed vulnerabilities, adversary capability assessments, and collaborative intelligence from partner organizations. All findings have been validated against multiple independent sources and cross-referenced with known threat actor methodologies."
        ]
    )

    # Intelligence Sections
    briefing.add_intelligence_section(
        title="THREAT ACTOR PROFILES",
        subsections=[
            ("Threat Group PHANTOM PROTOCOL",
             "Emerging state-sponsored collective with demonstrated capability for advanced persistent operations. Known for sophisticated social engineering and supply chain compromise vectors."),
            ("Threat Group CIPHER NETWORK",
             "Financial motivation drives this group. Primary focus on banking infrastructure and cryptocurrency platforms. Recently acquired offensive AI capabilities."),
            ("Threat Group SHADOW COLLECTIVE",
             "Historically focused on intellectual property theft. Evidence suggests expansion into critical infrastructure targeting.")
        ]
    )

    # Callouts
    briefing.add_callout(
        "AI systems represent both opportunity and risk. Current defensive posture is inadequate against emerging threats.",
        severity='alert'
    )

    briefing.add_callout(
        "CRITICAL: Intelligence suggests coordinated activity across multiple threat actors. This may indicate either resource sharing or synchronized campaign planning.",
        severity='critical'
    )

    # Data Table
    briefing.add_table(
        headers=['Threat Group', 'Origin', 'Capability Level', 'Primary Target'],
        data=[
            ['PHANTOM PROTOCOL', 'Eastern Europe', 'Advanced', 'Government & Defense'],
            ['CIPHER NETWORK', 'South Asia', 'Intermediate', 'Financial Services'],
            ['SHADOW COLLECTIVE', 'Unknown', 'Advanced', 'Technology Sector'],
            ['GHOST SYNDICATE', 'Multiple', 'Intermediate', 'Healthcare'],
        ]
    )

    # Recommendations
    briefing.add_section(
        title="STRATEGIC RECOMMENDATIONS",
        content=["The following prioritized recommendations are presented for consideration by strategic leadership:"]
    )

    briefing.add_recommendation(
        number=1,
        text="Establish AI Security Operations Center (AI-SOC) with dedicated personnel and resources for continuous monitoring",
        timeline="0-30 days (immediate action)"
    )

    briefing.add_recommendation(
        number=2,
        text="Implement enhanced cryptographic protocols for all critical infrastructure communications",
        timeline="30-90 days (urgent)"
    )

    briefing.add_recommendation(
        number=3,
        text="Deploy decoy systems and honeypots to detect and track advanced threat actors",
        timeline="60-120 days (priority)"
    )

    # Appendix
    briefing.add_appendix(
        title="APPENDIX A: SOURCES & CITATIONS",
        content=[
            "[1] NIST Cybersecurity Framework v2.1 - Federal Update Q1 2026",
            "[2] NSA Intelligence Assessment - AI Threat Modeling (CLASSIFIED)",
            "[3] International Cybersecurity Consortium - Quarterly Threat Report",
            "[4] Department of Defense Intelligence Analysis - Strategic Implications Study",
            "[5] Partner Intelligence Organization - Collaborative Assessment 2026-Q1"
        ]
    )

    # Generate PDF
    output_path = "/sessions/loving-zealous-carson/mnt/Opus Cowork/vault/SAMPLE_RESEARCH_BRIEFING.pdf"
    print(f"\nGenerating sample briefing...")
    briefing.generate(output_path)

    print(f"✓ PDF generated successfully at: {output_path}")
    print(f"✓ File size: {os.path.getsize(output_path) / 1024:.1f} KB")
    print("\n" + "=" * 80)
    print("DEMO COMPLETE - Report ready for review")
    print("=" * 80)
