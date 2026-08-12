# Returns policy and reason codes

Kata accepts unworn merchandise within 30 days with proof of purchase. The customer
policy is separate from the analytical reason code: ERPA uses the code to diagnose
product and fulfilment issues, never to assess an individual customer.

`size` means the stated size or garment block did not meet the customer's expectation.
`quality` covers material, construction or finishing faults. `damaged` is damage in
transit or before sale. `changed_mind` has no confirmed product defect. Analysts should
not merge quality and damage: the owners and corrective actions differ.

Return rate is returned units divided by sold units for the same product and window.
Show the minimum sample size and compare with its category and region. Flag at 1.5
times the category baseline with at least 30 sold units, or above 15% regardless of
baseline. Use net units and net revenue in sell-through and margin calculations.

TrueDenim currently has an abnormal `size` return rate and is under fit review. Surface
the issue in anomalies, but do not infer that all returns represent a defect or change
the size curve automatically. Break down style, region and size before recommending an
action.

All course customer IDs are synthetic and pseudonymised. ERPA may analyse aggregate
segments, repeat behaviour and return rates; it must not display or invent names,
addresses, email, payment details or other personal information. There is no write-back
to customer, order or return systems.
